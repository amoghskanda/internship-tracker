'use client';
/* oxlint-disable next/no-html-link-for-pages -- native navigation is required for the hosted Vinext route. */

import { SyntheticEvent, useEffect, useState } from 'react';
import { ArrowLeft, BriefcaseBusiness, CalendarDays } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  ACTIVE_APPLICATION_STATUSES,
  dateOnly,
  isRemoved,
  Job,
  loadTracker,
  saveApplication,
  safeUrl,
  STATUS_OPTIONS,
} from '@/lib/tracker';

export default function ApplicationsPage() {
  const [readOnly, setReadOnly] = useState(true),
    [example, setExample] = useState(false);
  const [jobs, setJobs] = useState<Job[]>([]),
    [selectedId, setSelectedId] = useState(''),
    [error, setError] = useState(''),
    [saved, setSaved] = useState(''),
    [saving, setSaving] = useState(false);
  useEffect(() => {
    void loadTracker()
      .then((result) => {
        setReadOnly(result.readOnly);
        setExample(result.example);
        const applied = result.jobs.filter(
          (job) =>
            !isRemoved(job) &&
            (Boolean(job.applied_date) ||
              ACTIVE_APPLICATION_STATUSES.has(job.status || '')),
        );
        setJobs(applied);
        const requested = new URLSearchParams(location.search).get('job');
        setSelectedId(
          requested && applied.some((job) => job.id === requested)
            ? requested
            : applied[0]?.id || '',
        );
      })
      .catch((caught) =>
        setError(
          caught instanceof Error
            ? caught.message
            : 'Applications could not be loaded.',
        ),
      );
  }, []);
  const selected = jobs.find((job) => job.id === selectedId);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (readOnly || !selected?.id) return;
    const form = new FormData(event.currentTarget);
    const fields = Object.fromEntries(
      [
        'status',
        'applied_date',
        'deadline',
        'oa_date',
        'interview_date',
        'notes',
      ].map((key) => {
        const value = form.get(key);
        return [key, typeof value === 'string' ? value : ''];
      }),
    );
    setSaving(true);
    setError('');
    setSaved('');
    try {
      await saveApplication(selected.id, fields);
      setJobs((rows) =>
        rows.map((job) =>
          job.id === selected.id ? { ...job, ...fields } : job,
        ),
      );
      setSaved('Saved');
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Application could not be saved.',
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <main className="applications-page">
      <header className="application-masthead">
        <a href="/">
          <ArrowLeft size={18} /> All openings
        </a>
        <div className="brand">
          <BriefcaseBusiness size={21} />
          <span>Application pipeline</span>
        </div>
        <span>{jobs.length} tracked</span>
      </header>
      <section className="application-heading">
        <p className="eyebrow">APPLIED ROLES</p>
        <h1>Keep every next step visible.</h1>
        <p>
          Track deadlines, assessments, interviews, and outcomes after you
          apply.
        </p>
      </section>
      {readOnly && (
        <output className="notice">
          {example
            ? 'Sample application records. These entries are fictional and editing is disabled.'
            : 'Read-only view. Application storage is not connected.'}
        </output>
      )}
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      <section className="pipeline-grid">
        <aside className="application-list" aria-label="Applied roles">
          {jobs.map((job) => (
            <button
              key={job.id}
              className={job.id === selectedId ? 'selected' : ''}
              onClick={() => {
                setSelectedId(job.id || '');
                setSaved('');
              }}
            >
              <span>{job.company}</span>
              <strong>{job.role}</strong>
              <small>
                {job.status || 'Applied'}
                {job.deadline ? ` · Due ${dateOnly(job.deadline)}` : ''}
              </small>
            </button>
          ))}
          {!jobs.length && (
            <div className="empty">
              <h3>No applications yet</h3>
              <p>Choose Applied on an opening to start tracking it here.</p>
            </div>
          )}
        </aside>
        <section className="application-editor">
          {selected ? (
            <form key={selected.id} onSubmit={submit}>
              <div className="editor-title">
                <div>
                  <p>{selected.company}</p>
                  <h2>{selected.role}</h2>
                </div>
                <a
                  href={safeUrl(selected.url)}
                  target="_blank"
                  rel="noreferrer"
                >
                  Open posting
                </a>
              </div>
              <fieldset className="form-grid" disabled={readOnly || saving}>
                <label htmlFor="status">
                  <span>Status</span>
                  <select
                    id="status"
                    name="status"
                    defaultValue={selected.status || 'Applied'}
                  >
                    {STATUS_OPTIONS.filter(
                      (value) => value !== 'Interested',
                    ).map((value) => (
                      <option key={value}>{value}</option>
                    ))}
                  </select>
                </label>
                <label htmlFor="applied-date">
                  <span>Applied date</span>
                  <Input
                    id="applied-date"
                    name="applied_date"
                    type="date"
                    defaultValue={selected.applied_date?.slice(0, 10) || ''}
                  />
                </label>
                <label htmlFor="deadline">
                  <span>Application deadline</span>
                  <Input
                    id="deadline"
                    name="deadline"
                    type="date"
                    defaultValue={selected.deadline?.slice(0, 10) || ''}
                  />
                </label>
                <label htmlFor="oa-date">
                  <span>OA date</span>
                  <Input
                    id="oa-date"
                    name="oa_date"
                    type="date"
                    defaultValue={selected.oa_date?.slice(0, 10) || ''}
                  />
                </label>
                <label htmlFor="interview-date">
                  <span>Interview date</span>
                  <Input
                    id="interview-date"
                    name="interview_date"
                    type="date"
                    defaultValue={selected.interview_date?.slice(0, 10) || ''}
                  />
                </label>
                <label className="notes-field" htmlFor="notes">
                  <span>Notes and next steps</span>
                  <textarea
                    id="notes"
                    name="notes"
                    defaultValue={selected.notes || ''}
                    placeholder="Recruiter, preparation notes, follow-up date…"
                  />
                </label>
              </fieldset>
              <div className="editor-footer">
                <span>{saved}</span>
                <Button type="submit" disabled={readOnly || saving}>
                  {saving ? 'Saving…' : 'Save application'}
                </Button>
              </div>
            </form>
          ) : (
            <div className="editor-empty">
              <CalendarDays size={30} />
              <h2>Select an application</h2>
              <p>Its dates and next steps will appear here.</p>
            </div>
          )}
        </section>
      </section>
    </main>
  );
}
