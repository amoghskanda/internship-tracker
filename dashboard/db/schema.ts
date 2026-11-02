import { integer, sqliteTable, text } from 'drizzle-orm/sqlite-core';

export const applications = sqliteTable('applications', {
  id: text('id').primaryKey(),
  status: text('status').notNull().default('Not applied'),
  appliedDate: text('applied_date').notNull().default(''),
  deadline: text('deadline').notNull().default(''),
  oaDate: text('oa_date').notNull().default(''),
  interviewDate: text('interview_date').notNull().default(''),
  notes: text('notes').notNull().default(''),
  manualPriorityOverride: text('manual_priority_override')
    .notNull()
    .default(''),
  removed: integer('removed', { mode: 'boolean' }).notNull().default(false),
  updatedAt: text('updated_at').notNull(),
});
