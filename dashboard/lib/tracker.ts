export type Job = {
  id?: string; company: string; role: string; domain?: string; url: string; job_id?: string;
  location?: string; jd?: string; skills?: string[] | string; visa_sponsorship?: string;
  visa_evidence?: string; source?: string; source_url?: string; date_posted?: string;
  discovered_at?: string; last_seen?: string; status?: string; applied_date?: string;
  deadline?: string; oa_date?: string; interview_date?: string; notes?: string;
  linkedin_contacts?: string; removed?: string | boolean | number;
  agent_tier?: string | number; match_score?: string | number; best_resume?: string;
  eligibility?: string; ranking_confidence?: string; ranking_confidence_reason?: string;
  strong_matches?: string[] | string; missing_requirements?: string[] | string;
  tailoring_suggestions?: string[] | string; ranking_explanation?: string;
  manual_priority_override?: string | number; resume_version?: string; scoring_version?: string;
  last_scored?: string;
};

export const STATUS_OPTIONS = ['Not applied', 'Interested', 'Applied', 'OA', 'Interviewing', 'Offer', 'Rejected', 'Withdrawn'];
export const ACTIVE_APPLICATION_STATUSES = new Set(['Applied', 'OA', 'Interviewing', 'Offer', 'Rejected', 'Withdrawn']);
export const RANKING_TIER_OPTIONS = ['All tiers', 'Tier 1', 'Tier 2', 'Tier 3', 'Tier 4', 'Ineligible'] as const;
export type RankingTier = Exclude<(typeof RANKING_TIER_OPTIONS)[number], 'All tiers'>;
export const words = (value: unknown) => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').join(', ') : typeof value === 'string' ? value : '';
export const lines = (value: unknown) => {
  if (Array.isArray(value)) return value.filter((item): item is string => typeof item === 'string' && item.trim() !== '').map(item => item.trim());
  if (typeof value !== 'string') return [];
  return value.split(/\r?\n|\s*;\s*|\s*,\s*/).map(item => item.trim()).filter(Boolean);
};
export const normalizeTier = (value: unknown): RankingTier | '' => {
  const raw = (typeof value === 'string' || typeof value === 'number' ? String(value) : '').trim().toLowerCase();
  if (!raw) return '';
  if (raw.includes('ineligible')) return 'Ineligible';
  const match = raw.match(/(?:tier\s*)?([1-4])(?:\b|$)/);
  return match ? `Tier ${match[1]}` as RankingTier : '';
};
export const effectiveTier = (job: Pick<Job, 'agent_tier' | 'manual_priority_override' | 'eligibility'>) => String(job.eligibility || '').toLowerCase() === 'ineligible' ? 'Ineligible' : normalizeTier(job.manual_priority_override) || normalizeTier(job.agent_tier);
export const tierRank = (tier: unknown) => {
  const normalized = normalizeTier(tier);
  return normalized === 'Ineligible' ? 5 : normalized ? Number(normalized.slice(-1)) : 6;
};
export const scoreValue = (value: unknown) => {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return undefined;
  const parsed = Number.parseFloat(value.replace('%', '').trim());
  return Number.isFinite(parsed) ? parsed : undefined;
};
export const formatMatchScore = (value: unknown) => {
  const score = scoreValue(value);
  if (score === undefined) return 'Not scored';
  const normalized = score >= 0 && score <= 1 ? score * 100 : score;
  return `${Math.round(normalized)}%`;
};
export const safeUrl = (value?: string) => { try { const url = new URL(value || ''); return ['https:', 'http:'].includes(url.protocol) ? url.href : undefined; } catch { return undefined; } };
export const dateOnly = (value?: string) => value?.match(/^\d{4}-\d{2}-\d{2}/)?.[0] || value || 'Not stated';
export const isRemoved = (job: Job) => ['true', '1', 'yes'].includes(String(job.removed || '').toLowerCase());
export const sourceLabel = (value?: string) => {
  const raw = String(value || '').split(',', 1)[0].trim();
  const key = raw.toLowerCase().split(':', 1)[0];
  return ({ simplify: 'Simplify', jobright: 'Jobright', instagram: 'Instagram', linkedin: 'LinkedIn', greenhouse: 'Greenhouse', ashby: 'Ashby', lever: 'Lever', workday: 'Workday' } as Record<string, string>)[key] || raw || 'Not stated';
};

export async function loadTracker() {
  const local = ['localhost', '127.0.0.1'].includes(location.hostname);
  let response = await fetch(local ? '/api/jobs' : '/tracker-data.json', { cache: 'no-store' });
  if (!local && !response.ok) response = await fetch('/tracker-data.example.json', { cache: 'no-store' });
  if (!response.ok) throw new Error('Tracker data is unavailable.');
  const data = await response.json() as { jobs?: Job[]; updated_at?: string; collected_at?: string } | Job[];
  let jobs = Array.isArray(data) ? data : data.jobs;
  if (!Array.isArray(jobs)) throw new Error('The tracker data could not be read.');
  if (!local) {
    const stateResponse = await fetch('/api/applications', { cache: 'no-store' });
    if (stateResponse.ok) {
      const state = await stateResponse.json() as { applications?: Array<Partial<Job> & { id: string }> };
      const byId = new Map((state.applications || []).map(item => [item.id, item]));
      jobs = jobs.map(job => job.id && byId.has(job.id) ? { ...job, ...byId.get(job.id) } : job);
    }
  }
  return { jobs, updated: Array.isArray(data) ? '' : data.updated_at || data.collected_at || '', local };
}

export async function saveApplication(id: string, fields: Partial<Job>, method: 'POST' | 'DELETE' = 'POST') {
  const response = await fetch('/api/applications', { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id, ...fields }) });
  const result = await response.json().catch(() => ({})) as { error?: string; application?: Partial<Job> };
  if (!response.ok) throw new Error(result.error || 'Application could not be saved.');
  return result.application;
}
