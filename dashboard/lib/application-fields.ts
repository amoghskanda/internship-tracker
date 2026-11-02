export const STATUS_OPTIONS = [
  'Not applied',
  'Interested',
  'Applied',
  'OA',
  'Interviewing',
  'Offer',
  'Rejected',
  'Withdrawn',
] as const;

export const ACTIVE_APPLICATION_STATUSES = new Set<string>([
  'Applied',
  'OA',
  'Interviewing',
  'Offer',
  'Rejected',
  'Withdrawn',
]);

export function applicationDate(
  status: string,
  previous = '',
  today = new Date().toISOString().slice(0, 10),
) {
  return ACTIVE_APPLICATION_STATUSES.has(status) ? previous || today : '';
}

export const DATE_KEYS = [
  'applied_date',
  'deadline',
  'oa_date',
  'interview_date',
] as const;
export const PRIORITY_OVERRIDES = [
  '',
  'Tier 1',
  'Tier 2',
  'Tier 3',
  'Tier 4',
] as const;

export type ApplicationPatch = Partial<
  Record<
    | (typeof DATE_KEYS)[number]
    | 'notes'
    | 'status'
    | 'manual_priority_override',
    string
  >
> & { removed?: boolean };

/** Validate the fields accepted by the hosted application API. */
export function parseApplicationRequest(body: unknown): {
  id: string;
  fields: ApplicationPatch;
} {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new Error('Request body must be a JSON object.');
  }
  const input = body as Record<string, unknown>;
  const id = typeof input.id === 'string' ? input.id.trim() : '';
  if (!id || id.length > 512) throw new Error('A valid job id is required.');

  const fields: ApplicationPatch = {};
  if (input.status !== undefined) {
    if (
      typeof input.status !== 'string' ||
      !STATUS_OPTIONS.some((status) => status === input.status)
    ) {
      throw new Error('Unsupported application status.');
    }
    fields.status = input.status;
  }
  for (const key of DATE_KEYS) {
    const value = input[key];
    if (value === undefined) continue;
    if (typeof value !== 'string') throw new Error(`${key} must be text.`);
    if (
      value &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        !Number.isFinite(Date.parse(value)) ||
        new Date(value).toISOString().slice(0, 10) !== value)
    ) {
      throw new Error(`${key} must be a valid date in YYYY-MM-DD format.`);
    }
    fields[key] = value;
  }
  if (input.notes !== undefined) {
    if (typeof input.notes !== 'string' || input.notes.length > 4000)
      throw new Error('Notes must be text with at most 4,000 characters.');
    fields.notes = input.notes;
  }
  if (input.manual_priority_override !== undefined) {
    if (
      typeof input.manual_priority_override !== 'string' ||
      !PRIORITY_OVERRIDES.some(
        (tier) => tier === input.manual_priority_override,
      )
    ) {
      throw new Error('Unsupported priority override.');
    }
    fields.manual_priority_override = input.manual_priority_override;
  }
  if (input.removed !== undefined) {
    if (typeof input.removed !== 'boolean')
      throw new Error('Removed must be true or false.');
    fields.removed = input.removed;
  }
  return { id, fields };
}
