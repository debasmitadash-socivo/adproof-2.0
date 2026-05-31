// Platform-native targeting filter taxonomy + company-driven suggestions.
// Chip IDs are stable strings -- toggling them in the store gives us a flat
// Record<id, true> that we can both render and convert to a sentence for
// the audience matcher.

export interface FilterChip {
  id: string;
  label: string;
}

export interface FilterGroup {
  id: string;
  title: string;
  chips: FilterChip[];
}

export interface FilterCard {
  id: string;
  title: string;
  glyph: string;
  groups: FilterGroup[];
}

const c = (id: string, label: string): FilterChip => ({ id, label });

// ---------------- Meta (FB / IG) ----------------
export const META_FILTERS: FilterCard[] = [
  {
    id: 'meta-gender', title: 'Gender', glyph: '⚥',
    groups: [{ id: 'gender', title: '', chips: [
      c('gender:all', 'All'), c('gender:women', 'Women'), c('gender:men', 'Men'),
    ] }],
  },
  {
    id: 'meta-location', title: 'Location', glyph: '📍',
    groups: [{ id: 'location', title: '', chips: [
      c('location:us', 'United States'), c('location:uk', 'United Kingdom'),
      c('location:ca', 'Canada'), c('location:au', 'Australia'),
      c('location:in', 'India'), c('location:de', 'Germany'),
    ] }],
  },
  {
    id: 'meta-detailed', title: 'Detailed targeting (interests · behaviours · demographics)', glyph: '🎯',
    groups: [
      { id: 'beauty', title: 'Interests · Beauty & wellness', chips: [
        c('interest:skincare', 'Skincare'), c('interest:cosmetics', 'Cosmetics'),
        c('interest:beauty', 'Beauty & personal care'), c('interest:selfcare', 'Self-care'),
      ] },
      { id: 'fashion', title: 'Interests · Fashion & lifestyle', chips: [
        c('interest:fashion', 'Fashion'), c('interest:lifestyle', 'Lifestyle blogs'),
        c('interest:streetwear', 'Streetwear'), c('interest:sustainable_fashion', 'Sustainable fashion'),
      ] },
      { id: 'fitness', title: 'Interests · Fitness, sports & outdoors', chips: [
        c('interest:fitness', 'Fitness'), c('interest:running', 'Running'),
        c('interest:cycling', 'Cycling'), c('interest:yoga', 'Yoga'),
        c('interest:hiking', 'Hiking & outdoors'), c('interest:sports', 'Sports'),
      ] },
      { id: 'tech', title: 'Interests · Tech & gaming', chips: [
        c('interest:gaming', 'Mobile games'), c('interest:electronics', 'Consumer electronics'),
        c('interest:streaming', 'Streaming services'),
      ] },
      { id: 'food', title: 'Interests · Food & drink', chips: [
        c('interest:cooking', 'Cooking'), c('interest:coffee', 'Coffee'),
        c('interest:wine', 'Wine'), c('interest:healthy_eating', 'Healthy eating'),
        c('interest:vegan', 'Plant-based eating'), c('interest:meal_prep', 'Meal prep'),
      ] },
      { id: 'finance', title: 'Interests · Finance & business', chips: [
        c('interest:investing', 'Investing'), c('interest:personal_finance', 'Personal finance'),
        c('interest:entrepreneurship', 'Entrepreneurship'),
        c('interest:startups', 'Startups & founders'),
        c('interest:saas', 'SaaS / software tools'),
        c('interest:marketing', 'Marketing & advertising'),
        c('interest:sales', 'Sales & business development'),
        c('interest:business_news', 'Business news (HBR, FT, Bloomberg)'),
      ] },
      { id: 'b2b_role', title: 'Behaviours · Professional / decision-makers', chips: [
        c('behaviour:smb_owner', 'Small business owner'),
        c('behaviour:agency_founder', 'Marketing / creative agency'),
        c('behaviour:freelancer', 'Freelancer / consultant'),
        c('behaviour:decision_maker', 'Business decision-makers'),
        c('behaviour:tech_early_adopter', 'Tech early adopters'),
      ] },
      { id: 'parent_family', title: 'Demographics · Parents & family', chips: [
        c('demo:parent_new', 'Parent of newborn (0–12 mo)'),
        c('demo:parent_toddler', 'Parent of toddler (1–4)'),
        c('demo:parent_teen', 'Parent of teen (13–17)'),
        c('demo:newlywed', 'Newly married'),
      ] },
      { id: 'behaviours', title: 'Behaviours · Purchasing', chips: [
        c('behaviour:engaged_shoppers', 'Engaged shoppers'),
        c('behaviour:online_buyers_30d', 'Online buyers (30d)'),
        c('behaviour:premium_brand', 'Premium brand affinity'),
      ] },
      { id: 'lifeevents', title: 'Demographics · Life events', chips: [
        c('life:new_parent', 'New parent'), c('life:recently_moved', 'Recently moved'),
        c('life:recently_engaged', 'Recently engaged'), c('life:in_relationship', 'In a relationship'),
      ] },
    ],
  },
  {
    id: 'meta-connection', title: 'Connection & custom audiences', glyph: '🔗',
    groups: [{ id: 'connection', title: '', chips: [
      c('audience:page_fans', 'Page fans'),
      c('audience:exclude_existing', 'Exclude existing customers'),
      c('audience:lookalike_1', 'Lookalike — top 1% buyers'),
      c('audience:lookalike_3', 'Lookalike — top 3% buyers'),
    ] }],
  },
];

// ---------------- LinkedIn ----------------
export const LINKEDIN_FILTERS: FilterCard[] = [
  {
    id: 'li-job', title: 'Job title & function', glyph: '💼',
    groups: [
      { id: 'titles', title: 'Job titles', chips: [
        c('jobtitle:head_of_growth', 'Head of Growth'),
        c('jobtitle:marketing_director', 'Marketing Director'),
        c('jobtitle:vp_marketing', 'VP Marketing'),
        c('jobtitle:cmo', 'CMO'),
        c('jobtitle:demand_gen', 'Demand Gen Manager'),
        c('jobtitle:founder_ceo', 'Founder / CEO'),
        c('jobtitle:product_manager', 'Product Manager'),
      ] },
      { id: 'function', title: 'Job function', chips: [
        c('function:marketing', 'Marketing'), c('function:sales', 'Sales'),
        c('function:product', 'Product'), c('function:operations', 'Operations'),
        c('function:finance', 'Finance'), c('function:hr', 'HR'),
      ] },
    ],
  },
  {
    id: 'li-seniority', title: 'Seniority', glyph: '🎖',
    groups: [{ id: 'seniority', title: '', chips: [
      c('seniority:entry', 'Entry'), c('seniority:senior', 'Senior'),
      c('seniority:manager', 'Manager'), c('seniority:director', 'Director'),
      c('seniority:vp', 'VP'), c('seniority:cxo', 'CXO'), c('seniority:owner', 'Owner'),
    ] }],
  },
  {
    id: 'li-company', title: 'Company', glyph: '🏢',
    groups: [
      { id: 'cosize', title: 'Size', chips: [
        c('cosize:1_10', '1–10'), c('cosize:11_50', '11–50'),
        c('cosize:51_200', '51–200'), c('cosize:201_500', '201–500'),
        c('cosize:501_1000', '501–1000'), c('cosize:1001_5000', '1001–5000'),
        c('cosize:5000_plus', '5000+'),
      ] },
      { id: 'industry', title: 'Industry', chips: [
        c('industry:marketing', 'Marketing & advertising'),
        c('industry:beauty', 'Beauty'), c('industry:ecommerce', 'E-commerce'),
        c('industry:saas', 'SaaS'), c('industry:finance', 'Financial services'),
        c('industry:healthcare', 'Healthcare'),
        c('industry:fitness', 'Fitness & wellness'),
      ] },
    ],
  },
];

// ---------------- Google ----------------
export const GOOGLE_FILTERS: FilterCard[] = [
  {
    id: 'g-affinity', title: 'Affinity audiences', glyph: '✨',
    groups: [{ id: 'affinity', title: '', chips: [
      c('affinity:beauty', 'Beauty mavens'),
      c('affinity:luxury', 'Shoppers · luxury'),
      c('affinity:health_fitness', 'Health & fitness buffs'),
      c('affinity:foodies', 'Foodies'),
      c('affinity:tech', 'Tech enthusiasts'),
      c('affinity:running', 'Avid runners'),
      c('affinity:cycling', 'Cycling enthusiasts'),
      c('affinity:outdoors', 'Outdoor enthusiasts'),
    ] }],
  },
  {
    id: 'g-inmarket', title: 'In-market audiences', glyph: '🛒',
    groups: [{ id: 'inmarket', title: '', chips: [
      c('inmarket:beauty', 'Beauty / Skincare'),
      c('inmarket:apparel', 'Apparel & accessories'),
      c('inmarket:electronics', 'Consumer electronics'),
      c('inmarket:travel', 'Travel'),
      c('inmarket:finance', 'Financial services'),
      c('inmarket:fitness_equipment', 'Fitness equipment'),
      c('inmarket:sports_apparel', 'Sportswear'),
    ] }],
  },
  {
    id: 'g-demos', title: 'Demographics', glyph: '👤',
    groups: [
      { id: 'age', title: 'Age', chips: [
        c('age:18_24', '18–24'), c('age:25_34', '25–34'), c('age:35_44', '35–44'),
        c('age:45_54', '45–54'), c('age:55_64', '55–64'), c('age:65_plus', '65+'),
      ] },
      { id: 'income', title: 'Household income', chips: [
        c('income:top_10', 'Top 10%'), c('income:11_20', '11–20%'),
        c('income:21_30', '21–30%'), c('income:31_40', '31–40%'),
      ] },
    ],
  },
];

// ----- Lookup by platform -----
export function filtersForPlatform(platformId: string): FilterCard[] {
  if (platformId.startsWith('meta_')) return META_FILTERS;
  if (platformId === 'linkedin') return LINKEDIN_FILTERS;
  if (platformId.startsWith('google_')) return GOOGLE_FILTERS;
  return META_FILTERS;
}

// ----- Company-driven suggestions -----
// Auto-applied when the user lands on Step 3 so the wizard never starts blank
// for a brand whose category is already known.
export function suggestedChips(category: string, platformId: string): string[] {
  const isMeta = platformId.startsWith('meta_');
  const isLi = platformId === 'linkedin';
  const isG = platformId.startsWith('google_');

  // Meta + Google share interest IDs; LinkedIn uses industry IDs.
  const META_GOOGLE_BY_CATEGORY: Record<string, string[]> = {
    beauty: isMeta
      ? ['interest:skincare', 'interest:cosmetics', 'interest:beauty', 'interest:selfcare', 'behaviour:engaged_shoppers', 'gender:women', 'location:us']
      : ['affinity:beauty', 'inmarket:beauty', 'age:25_34', 'age:35_44'],
    apparel: isMeta
      ? ['interest:fashion', 'interest:lifestyle', 'interest:sustainable_fashion', 'behaviour:engaged_shoppers']
      : ['inmarket:apparel', 'affinity:luxury'],
    fitness: isMeta
      ? ['interest:fitness', 'interest:running', 'interest:cycling', 'interest:yoga', 'interest:sports', 'behaviour:engaged_shoppers']
      : ['affinity:health_fitness', 'affinity:running', 'affinity:cycling', 'inmarket:fitness_equipment', 'inmarket:sports_apparel'],
    food_bev: isMeta
      ? ['interest:cooking', 'interest:coffee', 'interest:healthy_eating', 'behaviour:engaged_shoppers']
      : ['affinity:foodies'],
    electronics: isMeta
      ? ['interest:electronics', 'interest:gaming', 'interest:streaming']
      : ['affinity:tech', 'inmarket:electronics'],
    travel: isMeta
      ? ['interest:lifestyle']
      : ['inmarket:travel'],
    finance: isMeta
      ? ['interest:investing', 'interest:personal_finance', 'interest:business_news', 'behaviour:decision_maker']
      : ['inmarket:finance'],
    // B2B-ish categories: surface professional + agency interest tags
    saas: isMeta
      ? ['interest:saas', 'interest:marketing', 'interest:startups', 'behaviour:decision_maker', 'behaviour:tech_early_adopter']
      : ['affinity:tech'],
    marketing_agency: isMeta
      ? ['interest:marketing', 'interest:saas', 'interest:entrepreneurship', 'behaviour:agency_founder', 'behaviour:decision_maker']
      : ['affinity:tech'],
    professional_services: isMeta
      ? ['interest:business_news', 'interest:entrepreneurship', 'behaviour:smb_owner', 'behaviour:decision_maker']
      : [],
    home: isMeta ? ['interest:lifestyle', 'demo:newlywed'] : [],
    auto: isMeta ? ['interest:lifestyle'] : [],
    entertainment: isMeta ? ['interest:streaming'] : ['affinity:tech'],
    general: [],
  };

  const LINKEDIN_BY_CATEGORY: Record<string, string[]> = {
    beauty: ['industry:beauty', 'function:marketing'],
    apparel: ['industry:ecommerce', 'function:marketing'],
    fitness: ['industry:fitness', 'function:marketing'],
    finance: ['industry:finance', 'function:finance'],
    electronics: ['industry:saas'],
    food_bev: ['industry:ecommerce'],
    travel: ['function:marketing'],
    home: ['industry:ecommerce'],
    auto: ['function:sales'],
    entertainment: ['industry:saas'],
    general: ['function:marketing'],
  };

  const baseSet = isLi
    ? LINKEDIN_BY_CATEGORY[category] ?? LINKEDIN_BY_CATEGORY.general
    : (isMeta || isG)
      ? META_GOOGLE_BY_CATEGORY[category] ?? META_GOOGLE_BY_CATEGORY.general
      : [];
  return baseSet;
}

// Convert a set of selected chip IDs into a natural-language audience
// description the backend's matcher can read.
export function describeFilters(
  selectedIds: string[],
  platformId: string,
): string {
  if (selectedIds.length === 0) return '';
  const cards = filtersForPlatform(platformId);
  // Flat lookup: id -> label
  const labels: Record<string, string> = {};
  const groupOf: Record<string, string> = {};
  for (const card of cards) for (const g of card.groups) for (const ch of g.chips) {
    labels[ch.id] = ch.label;
    groupOf[ch.id] = g.title || card.title;
  }
  const bucketed: Record<string, string[]> = {};
  for (const id of selectedIds) {
    // Free-text interests added by the user come through as `custom:<text>`.
    if (id.startsWith('custom:')) {
      (bucketed['Custom interests'] ||= []).push(id.slice('custom:'.length));
      continue;
    }
    if (!labels[id]) continue;
    const bucket = groupOf[id] || 'Targeting';
    bucketed[bucket] ||= [];
    bucketed[bucket].push(labels[id]);
  }
  return Object.entries(bucketed)
    .map(([bucket, items]) => `${bucket}: ${items.join(', ')}`)
    .join('. ');
}
