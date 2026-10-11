import { env } from 'cloudflare:workers';

const STATUSES = new Set(['Not applied', 'Interested', 'Applied', 'OA', 'Interviewing', 'Offer', 'Rejected', 'Withdrawn']);
const PRIORITY_OVERRIDES = new Set(['', 'Tier 1', 'Tier 2', 'Tier 3', 'Tier 4']);
const DATE_KEYS = ['applied_date', 'deadline', 'oa_date', 'interview_date'] as const;

type Application = {
  id: string;
  status: string;
  applied_date: string;
  deadline: string;
  oa_date: string;
  interview_date: string;
  notes: string;
  manual_priority_override: string;
  removed: number | boolean;
  updated_at: string;
};

function database() {
  const db = (env as unknown as { DB?: D1Database }).DB;
  if (!db) throw new Error('Application storage is unavailable.');
  return db;
}

function json(data: unknown, status = 200) {
  return Response.json(data, { status, headers: { 'Cache-Control': 'no-store' } });
}

async function requestBody(request: Request) {
  const body = await request.json().catch(() => null) as Record<string, unknown> | null;
  if (!body || Array.isArray(body)) throw new Error('Request body must be a JSON object.');
  const id = typeof body.id === 'string' ? body.id.trim() : '';
  if (!id || id.length > 512) throw new Error('A valid job id is required.');
  const status = body.status === undefined ? undefined : typeof body.status === 'string' ? body.status : null;
  if (status === null) throw new Error('Status must be text.');
  if (status !== undefined && !STATUSES.has(status)) throw new Error('Unsupported application status.');
  const fields: Record<string, string | boolean | undefined> = { status };
  for (const key of DATE_KEYS) {
    const value = body?.[key];
    if (value !== undefined && typeof value !== 'string') throw new Error(`${key} must be text.`);
    if (typeof value === 'string' && value !== '' && !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error(`${key} must use YYYY-MM-DD.`);
    fields[key] = value;
  }
  if (body.notes !== undefined && typeof body.notes !== 'string') throw new Error('Notes must be text.');
  if (typeof body.notes === 'string' && body.notes.length > 4000) throw new Error('Notes must be 4,000 characters or fewer.');
  fields.notes = body.notes as string | undefined;
  if (body.manual_priority_override !== undefined && typeof body.manual_priority_override !== 'string') throw new Error('Priority override must be text.');
  if (typeof body.manual_priority_override === 'string' && !PRIORITY_OVERRIDES.has(body.manual_priority_override)) throw new Error('Unsupported priority override.');
  fields.manual_priority_override = body.manual_priority_override as string | undefined;
  if (body.removed !== undefined && typeof body.removed !== 'boolean') throw new Error('Removed must be true or false.');
  fields.removed = body.removed as boolean | undefined;
  return { fields, id, status };
}

export async function GET() {
  try {
    const result = await database().prepare('SELECT id, status, applied_date, deadline, oa_date, interview_date, notes, manual_priority_override, removed, updated_at FROM applications').all<Application>();
    return json({ applications: result.results });
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : 'Application records could not be loaded.' }, 500);
  }
}

export async function POST(request: Request) {
  try {
    const { fields, id, status } = await requestBody(request);
    const current = await database().prepare('SELECT id, status, applied_date, deadline, oa_date, interview_date, notes, manual_priority_override, removed, updated_at FROM applications WHERE id = ?').bind(id).first<Application>();
    const nextStatus = status ?? current?.status ?? 'Not applied';
    const today = new Date().toISOString().slice(0, 10);
    const appliedDate = fields.applied_date !== undefined ? fields.applied_date as string : current?.applied_date || (nextStatus !== 'Not applied' ? today : '');
    const values = {
      id,
      status: nextStatus,
      applied_date: nextStatus === 'Not applied' ? '' : appliedDate,
      deadline: fields.deadline !== undefined ? fields.deadline as string : current?.deadline || '',
      oa_date: fields.oa_date !== undefined ? fields.oa_date as string : current?.oa_date || '',
      interview_date: fields.interview_date !== undefined ? fields.interview_date as string : current?.interview_date || '',
      notes: fields.notes !== undefined ? fields.notes as string : current?.notes || '',
      manual_priority_override: fields.manual_priority_override !== undefined ? fields.manual_priority_override as string : current?.manual_priority_override || '',
      removed: fields.removed !== undefined ? fields.removed as boolean : Boolean(current?.removed),
      updated_at: new Date().toISOString(),
    };
    await database().prepare(`INSERT INTO applications (id, status, applied_date, deadline, oa_date, interview_date, notes, manual_priority_override, removed, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET status=excluded.status, applied_date=excluded.applied_date, deadline=excluded.deadline,
      oa_date=excluded.oa_date, interview_date=excluded.interview_date, notes=excluded.notes,
      manual_priority_override=excluded.manual_priority_override, removed=excluded.removed, updated_at=excluded.updated_at`)
      .bind(values.id, values.status, values.applied_date, values.deadline, values.oa_date, values.interview_date, values.notes, values.manual_priority_override, values.removed ? 1 : 0, values.updated_at).run();
    return json({ application: values });
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : 'Application record could not be saved.' }, 400);
  }
}

export async function DELETE(request: Request) {
  try {
    const { id } = await requestBody(request);
    const updatedAt = new Date().toISOString();
    await database().prepare(`INSERT INTO applications (id, removed, updated_at) VALUES (?, 1, ?)
      ON CONFLICT(id) DO UPDATE SET removed=1, updated_at=excluded.updated_at`).bind(id, updatedAt).run();
    return json({ id, removed: true, updated_at: updatedAt });
  } catch (error) {
    return json({ error: error instanceof Error ? error.message : 'Opening could not be removed.' }, 400);
  }
}
