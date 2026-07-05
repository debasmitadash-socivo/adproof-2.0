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
  moveCampaign as dbMoveCampaign,
  listCampaigns as dbListCampaigns,
  saveAudience as dbSaveAudience,
  deleteAudience as dbDeleteAudience,
  listAudiences as dbListAudiences,
  saveCompany as dbSaveCompany,
  createCompany as dbCreateCompany,
  deleteCompanyById as dbDeleteCompanyById,
  moveAudience as dbMoveAudience,
  listCompanies as dbListCompanies,
  claimPendingInvites as dbClaimPendingInvites,
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
  companyProfile: CompanyProfile | null;     // current workspace's profile
  setCompanyDescription: (s: string) => void;
  setCompanyProfile: (p: CompanyProfile | null) => void;

  // Multi-workspace: one user can manage several companies/clients. Each
  // workspace has its own campaigns / audiences / calibration.
  companies: CompanyProfile[];
  currentCompanyId: string | null;
  setCurrentCompany: (id: string) => Promise<void>;
  createWorkspace: (p: CompanyProfile) => Promise<string>;
  deleteWorkspace: (id: string) => Promise<void>;

  savedCampaigns: SavedCampaign[];
  addCampaign: (c: SavedCampaign) => void;
  deleteCampaign: (id: string) => void;
  moveCampaign: (id: string, targetCompanyId: string) => Promise<void>;

  savedAudiences: SavedAudience[];
  addAudience: (a: SavedAudience) => void;
  deleteAudience: (id: string) => void;
  moveAudience: (id: string, targetCompanyId: string) => Promise<void>;

  hydrated: boolean;
  setHydrated: (b: boolean) => void;

  // DB sync: true once we've loaded from / imported into Supabase (or decided
  // there's no DB). The app waits for this before the onboarding redirect so a
  // company that lives only in the DB isn't mistaken for "no company".
  dbSynced: boolean;
  syncFromDb: () => Promise<void>;
  // Set when syncFromDb (or a workspace reload) fails against Supabase, e.g.
  // an unapplied migration. Shown as a banner so a broken load doesn't just
  // look like "nothing happened".
  dbSyncError: string | null;

  resetAccount: () => void;

  // -- transient wizard state -------------------------------------------
  objective: 'awareness' | 'consideration' | 'conversion';
  setObjective: (o: AppState['objective']) => void;

  platformId: string;
  formatId: string;
  setPlatform: (pid: string) => void;
  setFormat: (fid: string) => void;
  // Additional placements to run the SAME creative on alongside the primary
  // format. Used for Meta cross-placement runs ("score this Reel on FB AND
  // IG") and any other "also try this placement" comparison. Each entry is
  // a format id from /api/platforms; on Run, each copy variant is expanded
  // into one run per (primary + additional) placement.
  additionalFormatIds: string[];
  toggleAdditionalFormat: (fid: string) => void;
  clearAdditionalFormats: () => void;

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
  additionalFormatIds: [] as string[],
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
        if (!p) { set({ companyProfile: null }); return; }
        // Stamp with the ACTIVE workspace id when the caller didn't supply one
        // (e.g. re-parsing the description builds a fresh profile with no id),
        // so we UPDATE the current workspace instead of silently spawning a
        // duplicate. Only genuinely create when there's no workspace at all.
        const id = p.id ?? get().currentCompanyId ?? undefined;
        if (id) {
          const stamped = { ...p, id };
          set((s) => ({
            companyProfile: stamped,
            companies: s.companies.some((c) => c.id === id)
              ? s.companies.map((c) => (c.id === id ? stamped : c))
              : [...s.companies, stamped],
          }));
          dbSaveCompany(stamped).catch((e) => console.error('[db] saveCompany', e));
        } else {
          set({ companyProfile: p });
          dbCreateCompany(p).then((newId) => {
            if (!newId) return;
            const withId = { ...p, id: newId };
            set((s) => ({
              companyProfile: withId,
              companies: s.companies.some((c) => c.id === newId) ? s.companies : [...s.companies, withId],
              currentCompanyId: s.currentCompanyId ?? newId,
            }));
          }).catch((e) => console.error('[db] createCompany', e));
        }
      },
      companies: [],
      currentCompanyId: null,
      setCurrentCompany: async (id) => {
        const cmp = get().companies.find((c) => c.id === id);
        if (!cmp) return;
        // Switch workspace: drop the previous workspace's data AND any transient
        // wizard/result state so one client's audience/campaign can't bleed into
        // another.
        set({
          currentCompanyId: id, companyProfile: cmp,
          savedCampaigns: [], savedAudiences: [],
          audienceSegment: null, audienceMatch: null,
          filterSelections: {}, currentCampaign: null, result: null,
        });
        // Reload the new workspace's data
        try {
          const [campaigns, audiences] = await Promise.all([
            dbListCampaigns(id), dbListAudiences(id),
          ]);
          set({ savedCampaigns: campaigns, savedAudiences: audiences });
        } catch (e) { console.error('[db] reload workspace', e); }
      },
      createWorkspace: async (p) => {
        // dbCreateCompany now throws on auth / RLS / network failures, so the
        // caller can show the actual reason instead of guessing why nothing
        // happened. Propagate by re-throwing.
        const id = await dbCreateCompany(p);
        const withId = { ...p, id };
        set((s) => ({
          companies: [...s.companies, withId],
          currentCompanyId: id,
          companyProfile: withId,
          savedCampaigns: [], savedAudiences: [],     // fresh workspace = empty data
        }));
        return id;
      },
      deleteWorkspace: async (id) => {
        // DB first (owner-only via RLS; FK cascades wipe its data). Only then
        // update local state and hop to another workspace — or back to
        // onboarding if none remain.
        await dbDeleteCompanyById(id);
        const remaining = get().companies.filter((c) => c.id !== id);
        set({ companies: remaining });
        if (get().currentCompanyId === id) {
          const next = remaining[0]?.id;
          if (next) await get().setCurrentCompany(next);
          else set({ currentCompanyId: null, companyProfile: null,
                     savedCampaigns: [], savedAudiences: [] });
        }
      },
      savedCampaigns: [],
      addCampaign: (c) => {
        // Tag every new campaign with the current workspace. Fall back to the
        // first workspace if currentCompanyId hasn't synced yet, so a campaign
        // is never saved unscoped (which would make it invisible everywhere).
        const st = get();
        const tagged = { ...c, companyId: c.companyId ?? st.currentCompanyId ?? st.companies[0]?.id ?? undefined };
        set((s) => ({ savedCampaigns: [tagged, ...s.savedCampaigns].slice(0, 200) }));
        dbSaveCampaign(tagged).catch((e) => console.error('[db] saveCampaign', e));
      },
      deleteCampaign: (id) => {
        set((s) => ({ savedCampaigns: s.savedCampaigns.filter((c) => c.id !== id) }));
        dbDeleteCampaign(id).catch((e) => console.error('[db] deleteCampaign', e));
      },
      moveCampaign: async (id, targetCompanyId) => {
        // DB first — only drop it from this workspace's list once the move
        // actually happened (a failed move must not hide the campaign).
        await dbMoveCampaign(id, targetCompanyId);
        set((s) => ({ savedCampaigns: s.savedCampaigns.filter((c) => c.id !== id) }));
      },
      savedAudiences: [],
      addAudience: (a) => {
        const st = get();
        const tagged = { ...a, companyId: a.companyId ?? st.currentCompanyId ?? st.companies[0]?.id ?? undefined };
        set((s) => ({ savedAudiences: [tagged, ...s.savedAudiences] }));
        dbSaveAudience(tagged).catch((e) => console.error('[db] saveAudience', e));
      },
      deleteAudience: (id) => {
        set((s) => ({ savedAudiences: s.savedAudiences.filter((a) => a.id !== id) }));
        dbDeleteAudience(id).catch((e) => console.error('[db] deleteAudience', e));
      },
      moveAudience: async (id, targetCompanyId) => {
        await dbMoveAudience(id, targetCompanyId);   // DB first — a failed move must not hide it
        set((s) => ({ savedAudiences: s.savedAudiences.filter((a) => a.id !== id) }));
      },
      hydrated: false,
      setHydrated: (b) => set({ hydrated: b }),
      dbSynced: false,
      dbSyncError: null,
      syncFromDb: async () => {
        try {
          const sb = getSupabase();
          if (!sb) { set({ dbSynced: true }); return; }
          const { data } = await sb.auth.getUser();
          if (!data.user) { set({ dbSynced: true }); return; }
          set({ dbSyncError: null });

          // Claim any workspace invites addressed to this email FIRST, so a
          // freshly shared workspace is already in the list we load below.
          try { await dbClaimPendingInvites(); }
          catch (e) { console.warn('[db] claimPendingInvites', e); }

          const local = get();
          let companies = await dbListCompanies();
          // Only a brand-new account (zero DB workspaces) is eligible for the
          // one-time localStorage import. Once the user has any DB workspace,
          // the DB is the source of truth and we must NOT re-import local data
          // (which would dump it into whatever workspace happens to be active).
          const firstEverAccount = companies.length === 0;

          // Bootstrap: recreate EVERY local workspace in the DB, not just the
          // active one — and remember old-id → new-id so campaigns/audiences
          // land in THEIR workspace. (The old single-workspace bootstrap
          // dumped every local campaign into whichever company was active:
          // that's how FC Construct campaigns ended up inside Men's Tee.)
          const importIdMap = new Map<string, string>();
          if (firstEverAccount) {
            const localCompanies = local.companies.length
              ? local.companies
              : (local.companyProfile ? [local.companyProfile] : []);
            for (const lc of localCompanies) {
              try {
                const newId = await dbCreateCompany(lc);
                if (lc.id) importIdMap.set(lc.id, newId);
              } catch (e) { console.error('[db] recreate workspace', e); }
            }
            if (localCompanies.length) companies = await dbListCompanies();
          }

          // Pick the active workspace: persisted choice (remapped if this was
          // an import) if still valid, else the first available company.
          let currentId = local.currentCompanyId
            ? (importIdMap.get(local.currentCompanyId) ?? local.currentCompanyId)
            : null;
          if (!currentId || !companies.some((c) => c.id === currentId)) {
            currentId = companies[0]?.id ?? null;
          }
          const currentCompany = companies.find((c) => c.id === currentId) ?? null;

          // Load the active workspace's data (if any).
          const [campaigns, audiences] = currentId
            ? await Promise.all([dbListCampaigns(currentId), dbListAudiences(currentId)])
            : [[], []];

          // One-time migration ONLY for a brand-new account: lift local
          // campaigns/audiences into the (single, just-created) workspace.
          let finalCampaigns: SavedCampaign[] = campaigns;
          if (firstEverAccount && currentId && local.savedCampaigns.length > 0) {
            const imported: SavedCampaign[] = [];
            for (const c of local.savedCampaigns) {
              // Route each campaign to ITS workspace via the id map; only the
              // genuinely untagged (pre-workspace era) fall to the active one.
              const mapped: string = (c.companyId && importIdMap.get(c.companyId)) || currentId;
              const cc = { ...c, id: isUuid(c.id) ? c.id : newId(), companyId: mapped };
              await dbSaveCampaign(cc);
              if (mapped === currentId) imported.push(cc);
            }
            finalCampaigns = imported;
          }
          let finalAudiences: SavedAudience[] = audiences;
          if (firstEverAccount && currentId && local.savedAudiences.length > 0) {
            const imp: SavedAudience[] = [];
            for (const a of local.savedAudiences) {
              const mapped: string = (a.companyId && importIdMap.get(a.companyId)) || currentId;
              const aa = { ...a, id: isUuid(a.id) ? a.id : newId(), companyId: mapped };
              await dbSaveAudience(aa);
              if (mapped === currentId) imp.push(aa);
            }
            finalAudiences = imp;
          }

          set({
            companies,
            currentCompanyId: currentId,
            companyProfile: currentCompany ?? local.companyProfile,
            savedCampaigns: finalCampaigns,
            savedAudiences: finalAudiences,
            dbSynced: true,
          });
        } catch (e) {
          console.error('[db] syncFromDb failed', e);
          set({ dbSynced: true, dbSyncError: (e as Error).message });
        }
      },
      resetAccount: () =>
        set({
          user: null,
          companyDescription: '',
          companyProfile: null,
          savedCampaigns: [],
          savedAudiences: [],
          dbSyncError: null,
          ...transientDefaults,
        }),

      // transient
      ...transientDefaults,
      setObjective: (o) => set({ objective: o }),
      setPlatform: (pid) => set({ platformId: pid, additionalFormatIds: [] }),
      setFormat: (fid) =>
        set((s) => ({
          formatId: fid,
          // If the new primary was previously sitting in the additional list,
          // drop it from there — a format can't be both primary and secondary.
          additionalFormatIds: s.additionalFormatIds.filter((id) => id !== fid),
        })),
      toggleAdditionalFormat: (fid) =>
        set((s) => {
          // The primary format is never an "additional" — guard that.
          if (fid === s.formatId) return {};
          const has = s.additionalFormatIds.includes(fid);
          return {
            additionalFormatIds: has
              ? s.additionalFormatIds.filter((id) => id !== fid)
              : [...s.additionalFormatIds, fid],
          };
        }),
      clearAdditionalFormats: () => set({ additionalFormatIds: [] }),
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
          if (next[chipId]) { delete next[chipId]; return { filterSelections: next }; }
          // Single-select groups (gender): turning one on clears its siblings,
          // so we never emit "Gender: All, Women, Men".
          for (const pre of ['gender:']) {
            if (chipId.startsWith(pre)) {
              for (const k of Object.keys(next)) if (k.startsWith(pre)) delete next[k];
            }
          }
          next[chipId] = true;
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
        // Multi-workspace: remember which workspace the user last had open.
        companies: state.companies,
        currentCompanyId: state.currentCompanyId,
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
