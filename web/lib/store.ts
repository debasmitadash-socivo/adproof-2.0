// Single Zustand store -- splits persisted account data (user, company,
// campaigns, audiences) from transient wizard state (which only matters
// while one analysis is being built).
import { create } from 'zustand';
import { persist, createJSONStorage } from 'zustand/middleware';
import type {
  AudienceMatch,
  CompanyProfile,
  SavedAudience,
  SavedCampaign,
  SimulateResponse,
  UserProfile,
  Variant,
} from './types';
import {
  saveCampaign as dbSaveCampaign,
  deleteCampaign as dbDeleteCampaign,
  listCampaigns as dbListCampaigns,
  saveAudience as dbSaveAudience,
  deleteAudience as dbDeleteAudience,
  listAudiences as dbListAudiences,
  saveCompany as dbSaveCompany,
  getCompany as dbGetCompany,
} from './db';
import { getSupabase } from './supabase';

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const isUuid = (s: string) => UUID_RE.test(s);
const newId = () =>
  (typeof crypto !== 'undefined' && crypto.randomUUID)
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

interface AppState {
  // -- persisted across sessions ----------------------------------------
  user: UserProfile | null;
  setUser: (u: UserProfile | null) => void;

  companyDescription: string;
  companyProfile: CompanyProfile | null;
  setCompanyDescription: (s: string) => void;
  setCompanyProfile: (p: CompanyProfile | null) => void;

  savedCampaigns: SavedCampaign[];
  addCampaign: (c: SavedCampaign) => void;
  deleteCampaign: (id: string) => void;

  savedAudiences: SavedAudience[];
  addAudience: (a: SavedAudience) => void;
  deleteAudience: (id: string) => void;

  hydrated: boolean;
  setHydrated: (b: boolean) => void;

  // DB sync: true once we've loaded from / imported into Supabase (or decided
  // there's no DB). The app waits for this before the onboarding redirect so a
  // company that lives only in the DB isn't mistaken for "no company".
  dbSynced: boolean;
  syncFromDb: () => Promise<void>;

  resetAccount: () => void;

  // -- transient wizard state -------------------------------------------
  objective: 'awareness' | 'consideration' | 'conversion';
  setObjective: (o: AppState['objective']) => void;

  platformId: string;
  formatId: string;
  setPlatform: (pid: string) => void;
  setFormat: (fid: string) => void;

  audienceDescription: string;
  audienceSegment: string | null;
  audienceMatch: AudienceMatch | null;
  setAudienceDescription: (s: string) => void;
  setAudienceSegment: (s: string | null) => void;
  setAudienceMatch: (m: AudienceMatch | null) => void;

  headline: string;
  primaryText: string;
  description: string;
  cta: string;
  link: string;
  setCreativeField: (
    k: 'headline' | 'primaryText' | 'description' | 'cta' | 'link',
    v: string,
  ) => void;

  imagePath: string | null;
  imageUrl: string | null;       // /uploads/... served by the API
  videoPath: string | null;
  videoUrl: string | null;
  setImage: (path: string | null, url: string | null) => void;
  setVideo: (path: string | null, url: string | null) => void;
  clearMedia: () => void;

  // Targeting filters -- chip id -> selected. Filter IDs are stable strings
  // (e.g. "interest:skincare", "location:us") so we can build a sentence
  // from them for the matcher.
  filterSelections: Record<string, true>;
  toggleFilter: (chipId: string) => void;
  clearFilters: () => void;
  setManyFilters: (chips: string[]) => void;

  // Multi-creative campaigns -- variants B, C, D in addition to "A" which
  // lives in the headline/primaryText/cta/link/imagePath fields above.
  extraVariants: Variant[];
  activeVariant: number;          // 0 = A (existing fields), 1..N = extras
  addVariant: () => void;
  removeVariant: (idx: number) => void;
  setActiveVariant: (idx: number) => void;
  updateExtraVariant: (idx: number, patch: Partial<Variant>) => void;

  budget: number;
  days: number;
  dailyReach: number;
  nRuns: number;
  setBudget: (n: number) => void;
  setDays: (n: number) => void;
  setDailyReach: (n: number) => void;
  setNRuns: (n: number) => void;

  step: number;
  setStep: (n: number) => void;

  result: SimulateResponse | null;
  setResult: (r: SimulateResponse | null) => void;

  currentCampaign: SavedCampaign | null;
  setCurrentCampaign: (c: SavedCampaign | null) => void;

  resetWizard: () => void;
}

const transientDefaults = {
  objective: 'consideration' as const,
  platformId: 'meta_instagram',
  formatId: 'meta_ig_reels',
  audienceDescription: '',
  audienceSegment: null,
  audienceMatch: null,
  headline: '',
  primaryText: '',
  description: '',
  cta: '',
  link: '',
  imagePath: null,
  imageUrl: null,
  videoPath: null,
  videoUrl: null,
  filterSelections: {} as Record<string, true>,
  extraVariants: [] as Variant[],
  activeVariant: 0,
  budget: 5000,
  days: 14,
  dailyReach: 0.35,
  nRuns: 20,
  step: 1,
  result: null,
  currentCampaign: null,
};

export const useApp = create<AppState>()(
  persist(
    (set, get) => ({
      // persisted
      user: null,
      setUser: (u) => set({ user: u }),
      companyDescription: '',
      companyProfile: null,
      setCompanyDescription: (s) => set({ companyDescription: s }),
      setCompanyProfile: (p) => {
        set({ companyProfile: p });
        if (p) dbSaveCompany(p).catch((e) => console.error('[db] saveCompany', e));
      },
      savedCampaigns: [],
      addCampaign: (c) => {
        set((s) => ({ savedCampaigns: [c, ...s.savedCampaigns].slice(0, 200) }));
        dbSaveCampaign(c).catch((e) => console.error('[db] saveCampaign', e));
      },
      deleteCampaign: (id) => {
        set((s) => ({ savedCampaigns: s.savedCampaigns.filter((c) => c.id !== id) }));
        dbDeleteCampaign(id).catch((e) => console.error('[db] deleteCampaign', e));
      },
      savedAudiences: [],
      addAudience: (a) => {
        set((s) => ({ savedAudiences: [a, ...s.savedAudiences] }));
        dbSaveAudience(a).catch((e) => console.error('[db] saveAudience', e));
      },
      deleteAudience: (id) => {
        set((s) => ({ savedAudiences: s.savedAudiences.filter((a) => a.id !== id) }));
        dbDeleteAudience(id).catch((e) => console.error('[db] deleteAudience', e));
      },
      hydrated: false,
      setHydrated: (b) => set({ hydrated: b }),
      dbSynced: false,
      syncFromDb: async () => {
        try {
          const sb = getSupabase();
          if (!sb) { set({ dbSynced: true }); return; }
          const { data } = await sb.auth.getUser();
          if (!data.user) { set({ dbSynced: true }); return; }
          const local = get();
          let [campaigns, audiences, company] = await Promise.all([
            dbListCampaigns(), dbListAudiences(), dbGetCompany(),
          ]);
          // One-time import: if the DB is empty but the browser has data, push
          // it up (regenerating any non-UUID ids) so nothing is lost.
          if (campaigns.length === 0 && local.savedCampaigns.length > 0) {
            const imported: SavedCampaign[] = [];
            for (const c of local.savedCampaigns) {
              const cc = isUuid(c.id) ? c : { ...c, id: newId() };
              await dbSaveCampaign(cc);
              imported.push(cc);
            }
            campaigns = imported;
          }
          if (audiences.length === 0 && local.savedAudiences.length > 0) {
            const imp: SavedAudience[] = [];
            for (const a of local.savedAudiences) {
              const aa = isUuid(a.id) ? a : { ...a, id: newId() };
              await dbSaveAudience(aa);
              imp.push(aa);
            }
            audiences = imp;
          }
          if (!company && local.companyProfile) {
            await dbSaveCompany(local.companyProfile);
            company = local.companyProfile;
          }
          set({
            savedCampaigns: campaigns.length ? campaigns : local.savedCampaigns,
            savedAudiences: audiences.length ? audiences : local.savedAudiences,
            companyProfile: company ?? local.companyProfile,
            dbSynced: true,
          });
        } catch (e) {
          console.error('[db] syncFromDb failed', e);
          set({ dbSynced: true });   // never block the app on a DB hiccup
        }
      },
      resetAccount: () =>
        set({
          user: null,
          companyDescription: '',
          companyProfile: null,
          savedCampaigns: [],
          savedAudiences: [],
          ...transientDefaults,
        }),

      // transient
      ...transientDefaults,
      setObjective: (o) => set({ objective: o }),
      setPlatform: (pid) => set({ platformId: pid }),
      setFormat: (fid) => set({ formatId: fid }),
      setAudienceDescription: (s) => set({ audienceDescription: s }),
      setAudienceSegment: (s) => set({ audienceSegment: s }),
      setAudienceMatch: (m) => set({ audienceMatch: m }),
      setCreativeField: (k, v) =>
        set((prev) => ({ ...prev, [k]: v }) as Partial<AppState>),
      setImage: (path, url) => set({ imagePath: path, imageUrl: url }),
      setVideo: (path, url) => set({ videoPath: path, videoUrl: url }),
      clearMedia: () => set({ imagePath: null, imageUrl: null, videoPath: null, videoUrl: null }),
      addVariant: () =>
        set((s) => {
          if (s.extraVariants.length >= 3) return {};   // cap at 4 total (A + B/C/D)
          const labels = ['B', 'C', 'D'];
          const idx = s.extraVariants.length;
          const v: Variant = {
            id: `v_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
            label: labels[idx] ?? `V${idx + 2}`,
            headline: '', primaryText: '', description: '', cta: '', link: '',
            imagePath: null, imageUrl: null, videoPath: null, videoUrl: null,
          };
          return {
            extraVariants: [...s.extraVariants, v],
            activeVariant: idx + 1,
          };
        }),
      removeVariant: (idx) =>
        set((s) => {
          if (idx < 1) return {};
          const realIdx = idx - 1;
          const next = s.extraVariants.filter((_, i) => i !== realIdx);
          // Relabel remaining: B, C, D
          const labels = ['B', 'C', 'D'];
          const relabelled = next.map((v, i) => ({ ...v, label: labels[i] ?? v.label }));
          return {
            extraVariants: relabelled,
            activeVariant: Math.max(0, idx - 1),
          };
        }),
      setActiveVariant: (idx) => set({ activeVariant: idx }),
      updateExtraVariant: (idx, patch) =>
        set((s) => ({
          extraVariants: s.extraVariants.map((v, i) =>
            i === idx ? { ...v, ...patch } : v),
        })),
      toggleFilter: (chipId) =>
        set((s) => {
          const next = { ...s.filterSelections };
          if (next[chipId]) delete next[chipId];
          else next[chipId] = true;
          return { filterSelections: next };
        }),
      clearFilters: () => set({ filterSelections: {} }),
      setManyFilters: (chips) =>
        set({
          filterSelections: Object.fromEntries(
            chips.map((c) => [c, true]),
          ) as Record<string, true>,
        }),
      setBudget: (n) => set({ budget: n }),
      setDays: (n) => set({ days: n }),
      setDailyReach: (n) => set({ dailyReach: n }),
      setNRuns: (n) => set({ nRuns: n }),
      setStep: (n) => set({ step: n }),
      setResult: (r) => set({ result: r }),
      setCurrentCampaign: (c) => set({ currentCampaign: c }),
      resetWizard: () => set({ ...transientDefaults }),
    }),
    {
      name: 'adproof-account-v1',
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        user: state.user,
        companyDescription: state.companyDescription,
        companyProfile: state.companyProfile,
        savedCampaigns: state.savedCampaigns,
        savedAudiences: state.savedAudiences,
      }),
      onRehydrateStorage: () => (s) => s?.setHydrated(true),
    },
  ),
);

// Display helpers
export function userInitials(name: string): string {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return 'U';
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export function workspaceLabel(profile: CompanyProfile | null): string {
  return profile?.company_name?.trim() || 'My workspace';
}
