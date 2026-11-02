import { env } from 'cloudflare:workers';

import {
  applicationDate,
  parseApplicationRequest,
} from '@/lib/application-fields';

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
  return Response.json(data, {
    status,
    headers: { 'Cache-Control': 'no-store' },
  });
}

async function requestBody(request: Request) {
  const body: unknown = await request.json().catch(() => null);
  return parseApplicationRequest(body);
}

function storageError(error: unknown) {
  console.error('Application storage operation failed:', error);
  return json({ error: 'Application storage is unavailable.' }, 503);
}

export async function GET() {
  try {
    const result = await database()
      .prepare(
        'SELECT id, status, applied_date, deadline, oa_date, interview_date, notes, manual_priority_override, removed, updated_at FROM applications',
      )
      .all<Application>();
    return json({ applications: result.results });
  } catch (error) {
    return storageError(error);
  }
}

export async function POST(request: Request) {
  let parsed: ReturnType<typeof parseApplicationRequest>;
  try {
    parsed = await requestBody(request);
  } catch (error) {
    return json(
      {
        error:
          error instanceof Error
            ? error.message
            : 'Invalid application request.',
      },
      400,
    );
  }
  try {
    const { fields, id } = parsed;
    const current = await database()
      .prepare(
        'SELECT id, status, applied_date, deadline, oa_date, interview_date, notes, manual_priority_override, removed, updated_at FROM applications WHERE id = ?',
      )
      .bind(id)
      .first<Application>();
    const nextStatus = fields.status ?? current?.status ?? 'Not applied';
    const appliedDate = applicationDate(
      nextStatus,
      fields.applied_date ?? current?.applied_date ?? '',
    );
    const values = {
      id,
      status: nextStatus,
      applied_date: appliedDate,
      deadline:
        fields.deadline !== undefined
          ? fields.deadline
          : current?.deadline || '',
      oa_date:
        fields.oa_date !== undefined ? fields.oa_date : current?.oa_date || '',
      interview_date:
        fields.interview_date !== undefined
          ? fields.interview_date
          : current?.interview_date || '',
      notes: fields.notes !== undefined ? fields.notes : current?.notes || '',
      manual_priority_override:
        fields.manual_priority_override !== undefined
          ? fields.manual_priority_override
          : current?.manual_priority_override || '',
      removed:
        fields.removed !== undefined
          ? fields.removed
          : Boolean(current?.removed),
      updated_at: new Date().toISOString(),
    };
    await database()
      .prepare(`INSERT INTO applications (id, status, applied_date, deadline, oa_date, interview_date, notes, manual_priority_override, removed, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET status=excluded.status, applied_date=excluded.applied_date, deadline=excluded.deadline,
      oa_date=excluded.oa_date, interview_date=excluded.interview_date, notes=excluded.notes,
      manual_priority_override=excluded.manual_priority_override, removed=excluded.removed, updated_at=excluded.updated_at`)
      .bind(
        values.id,
        values.status,
        values.applied_date,
        values.deadline,
        values.oa_date,
        values.interview_date,
        values.notes,
        values.manual_priority_override,
        values.removed ? 1 : 0,
        values.updated_at,
      )
      .run();
    return json({ application: values });
  } catch (error) {
    return storageError(error);
  }
}

export async function DELETE(request: Request) {
  let parsed: ReturnType<typeof parseApplicationRequest>;
  try {
    parsed = await requestBody(request);
  } catch (error) {
    return json(
      {
        error:
          error instanceof Error
            ? error.message
            : 'Invalid application request.',
      },
      400,
    );
  }
  try {
    const { id } = parsed;
    const updatedAt = new Date().toISOString();
    await database()
      .prepare(`INSERT INTO applications (id, removed, updated_at) VALUES (?, 1, ?)
      ON CONFLICT(id) DO UPDATE SET removed=1, updated_at=excluded.updated_at`)
      .bind(id, updatedAt)
      .run();
    return json({ id, removed: true, updated_at: updatedAt });
  } catch (error) {
    return storageError(error);
  }
}
