'use client';
/* oxlint-disable next/no-html-link-for-pages -- native navigation is required for the hosted Vinext route. */

import { useEffect, useState } from 'react';
import {
  ArrowUpRight,
  BriefcaseBusiness,
  FileSpreadsheet,
  RefreshCw,
  Search,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Pagination,
  PaginationContent,
  PaginationItem,
} from '@/components/ui/pagination';
import { JobTable } from '@/components/job-table';
import { JobDetails } from '@/components/job-details';
import {
  ACTIVE_APPLICATION_STATUSES,
  applicationDate,
  effectiveTier,
  isRemoved,
  Job,
  loadTracker,
  RANKING_TIER_OPTIONS,
  saveApplication,
  scoreValue,
  sourceLabel,
  tierRank,
  words,
} from '@/lib/tracker';

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]),
    [query, setQuery] = useState(''),
    [view, setView] = useState('All roles');
  const [domain, setDomain] = useState('All domains'),
    [source, setSource] = useState('All sources'),
    [tier, setTier] = useState('All tiers');
  const [selected, setSelected] = useState<Job | null>(null),
    [mode, setMode] = useState('Loading'),
    [updated, setUpdated] = useState(''),
    [error, setError] = useState('');
  const [readOnly, setReadOnly] = useState(true),
    [example, setExample] = useState(false);
  const [mailReady, setMailReady] = useState(false),
    [savingId, setSavingId] = useState(''),
    [rankingSavingId, setRankingSavingId] = useState(''),
    [page, setPage] = useState(1);

  async function refresh() {
    try {
      const result = await loadTracker();
      setJobs(result.jobs);
      setUpdated(result.updated);
      setReadOnly(result.readOnly);
      setExample(result.example);
      setMode(
        result.example
          ? 'Sample data'
          : result.local
            ? 'Live on your Mac'
            : 'Synced online',
      );
      setError('');
      if (result.local) {
        try {
          const response = await fetch('/api/status', { cache: 'no-store' });
          if (response.ok) {
            const status = (await response.json()) as {
              email_configured?: boolean;
            };
            setMailReady(Boolean(status.email_configured));
          }
        } catch {}
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Refresh failed.');
    }
  }

  async function changeStatus(job: Job, status: string) {
    if (readOnly || !job.id) return;
    setSavingId(job.id);
    setError('');
    try {
      const appliedDate = applicationDate(status, job.applied_date);
      await saveApplication(job.id, { status, applied_date: appliedDate });
      setJobs((rows) =>
        rows.map((row) =>
          row.id === job.id
            ? { ...row, status, applied_date: appliedDate }
            : row,
        ),
      );
      if (status === 'Applied')
        window.location.assign(
          `/applications?job=${encodeURIComponent(job.id)}`,
        );
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Status could not be saved.',
      );
    } finally {
      setSavingId('');
    }
  }

  async function removeJob(job: Job) {
    if (readOnly || !job.id) return;
    setSavingId(job.id);
    setError('');
    try {
      await saveApplication(job.id, {}, 'DELETE');
      setJobs((rows) => rows.filter((row) => row.id !== job.id));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Opening could not be removed.',
      );
    } finally {
      setSavingId('');
    }
  }

  async function changePriority(job: Job, override: string) {
    if (readOnly || !job.id) return;
    setRankingSavingId(job.id);
    setError('');
    try {
      await saveApplication(job.id, { manual_priority_override: override });
      setJobs((rows) =>
        rows.map((row) =>
          row.id === job.id
            ? { ...row, manual_priority_override: override }
            : row,
        ),
      );
      setSelected((row) => {
        if (!row || row.id !== job.id) return row;
        return { ...row, manual_priority_override: override };
      });
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : 'Priority override could not be saved.',
      );
    } finally {
      setRankingSavingId('');
    }
  }

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(refresh, 60000);
    return () => {
      clearTimeout(initial);
      clearInterval(timer);
    };
  }, []);
  const activeJobs = jobs.filter((job) => !isRemoved(job));
  const pending = activeJobs.filter(
    (job) =>
      !job.applied_date &&
      !ACTIVE_APPLICATION_STATUSES.has(job.status || 'Not applied'),
  );
  const applied = activeJobs.filter(
    (job) =>
      Boolean(job.applied_date) ||
      ACTIVE_APPLICATION_STATUSES.has(job.status || ''),
  );
  const domains = [
    ...new Set(
      activeJobs
        .map((job) => job.domain)
        .filter((value): value is string => Boolean(value)),
    ),
  ].sort();
  const sources = [
    ...new Set(activeJobs.map((job) => sourceLabel(job.source))),
  ].sort();
  const filtered = activeJobs
    .filter(
      (job) =>
        (view !== 'Not applied' || pending.includes(job)) &&
        (view !== 'Applied' || applied.includes(job)) &&
        (view !== 'Sponsorship provided' ||
          job.visa_sponsorship === 'provided') &&
        (domain === 'All domains' || job.domain === domain) &&
        (source === 'All sources' || sourceLabel(job.source) === source) &&
        (tier === 'All tiers' || effectiveTier(job) === tier) &&
        `${job.company} ${job.role} ${job.domain} ${job.location} ${words(job.skills)} ${sourceLabel(job.source)} ${job.best_resume || ''} ${words(job.strong_matches)} ${words(job.missing_requirements)}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    )
    .sort((first, second) => {
      const tierDifference =
        tierRank(effectiveTier(first)) - tierRank(effectiveTier(second));
      if (tierDifference) return tierDifference;
      const scoreDifference =
        (scoreValue(second.match_score) ?? -Infinity) -
        (scoreValue(first.match_score) ?? -Infinity);
      if (scoreDifference) return scoreDifference;
      return `${first.company} ${first.role}`.localeCompare(
        `${second.company} ${second.role}`,
      );
    });
  const pages = Math.max(1, Math.ceil(filtered.length / 50)),
    currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * 50, currentPage * 50);

  return (
    <main className="tracker">
      <header className="masthead">
        <div className="brand">
          <BriefcaseBusiness size={22} />
          <span>Internship desk</span>
        </div>
        <span className="season">SUMMER / 2027</span>
        <a className="owner" href="/applications">
          Application pipeline
        </a>
      </header>
      <section className="heading">
        <div>
          <p className="eyebrow">APPLICATION TRACKER</p>
          <h1>Applications, in view.</h1>
          <p className="intro">Your summer 2027 opportunities.</p>
        </div>
        <div className="heading-actions">
          <a className="secondary-action" href="/applications">
            Track applied roles
          </a>
          <a
            className="download"
            href={
              mode === 'Live on your Mac'
                ? '/api/workbook'
                : '/Summer-2027-Internships.xlsx'
            }
            download
          >
            <FileSpreadsheet size={19} /> Download Excel{' '}
            <ArrowUpRight size={17} />
          </a>
        </div>
      </section>
      <section className="metrics" aria-label="Application summary">
        <div>
          <span>Tracked openings</span>
          <strong>{activeJobs.length.toLocaleString()}</strong>
          <small>Summer 2027</small>
        </div>
        <div>
          <span>Ready to apply</span>
          <strong>{pending.length.toLocaleString()}</strong>
          <small>Not applied yet</small>
        </div>
        <div>
          <span>Applications sent</span>
          <strong>{applied.length.toLocaleString()}</strong>
          <small>
            <a href="/applications">View pipeline</a>
          </small>
        </div>
        <div className="schedule">
          <span>Daily search</span>
          <strong>
            7:00<span>am</span>
          </strong>
          <small>Pacific time · Mac must be awake</small>
        </div>
      </section>
      <section className="workspace">
        <div className="workspace-head">
          <div>
            <h2>
              Your opportunities <span>{filtered.length}</span>
            </h2>
            <p>
              Sorted by application tier and match score.{' '}
              {readOnly
                ? 'Browse role details and ranking evidence.'
                : 'Status changes save immediately.'}
            </p>
          </div>
          <Button variant="outline" onClick={refresh}>
            <RefreshCw size={15} /> Refresh
          </Button>
        </div>
        <div className="controls">
          <nav aria-label="Filter applications">
            {[
              'All roles',
              'Not applied',
              'Applied',
              'Sponsorship provided',
            ].map((value) => (
              <button
                key={value}
                aria-pressed={view === value}
                className={view === value ? 'active' : ''}
                onClick={() => {
                  setView(value);
                  setPage(1);
                }}
              >
                {value}
              </button>
            ))}
          </nav>
          <div className="control-fields">
            <label className="domain-filter" htmlFor="tier-filter">
              <span>Tier</span>
              <select
                id="tier-filter"
                value={tier}
                onChange={(event) => {
                  setTier(event.target.value);
                  setPage(1);
                }}
              >
                {RANKING_TIER_OPTIONS.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="domain-filter" htmlFor="domain-filter">
              <span>Domain</span>
              <select
                id="domain-filter"
                value={domain}
                onChange={(event) => {
                  setDomain(event.target.value);
                  setPage(1);
                }}
              >
                <option>All domains</option>
                {domains.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <label className="domain-filter" htmlFor="source-filter">
              <span>Source</span>
              <select
                id="source-filter"
                value={source}
                onChange={(event) => {
                  setSource(event.target.value);
                  setPage(1);
                }}
              >
                <option>All sources</option>
                {sources.map((value) => (
                  <option key={value}>{value}</option>
                ))}
              </select>
            </label>
            <div className="search">
              <Search size={17} />
              <Input
                aria-label="Search roles, companies, domains, sources, skills or resumes"
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setPage(1);
                }}
                placeholder="Search roles, companies, skills"
              />
            </div>
          </div>
        </div>
        {example && (
          <output className="notice">
            Sample data. These companies, roles, and application records are
            fictional. Editing is disabled.
          </output>
        )}
        {!example && readOnly && (
          <output className="notice">
            Read-only view. Application storage is not connected.
          </output>
        )}
        {error && (
          <p role="alert" className="notice">
            {error}
          </p>
        )}
        <JobTable
          jobs={visible}
          readOnly={readOnly}
          savingId={savingId}
          local={mode === 'Live on your Mac'}
          onSelect={setSelected}
          onStatusChange={changeStatus}
          onRemove={removeJob}
        />
        {!filtered.length && (
          <div className="empty">
            <h3>
              {activeJobs.length
                ? 'No matching openings'
                : 'Waiting for the first search'}
            </h3>
            <p>
              {activeJobs.length
                ? 'Try another tier, company, role, source, or skill.'
                : 'Verified summer 2027 openings will appear here after collection.'}
            </p>
          </div>
        )}
        {filtered.length > 50 && (
          <Pagination className="page-controls">
            <PaginationContent>
              <PaginationItem>
                <Button
                  variant="outline"
                  disabled={currentPage === 1}
                  onClick={() => setPage(currentPage - 1)}
                >
                  Previous
                </Button>
              </PaginationItem>
              <PaginationItem>
                <span className="page-count">
                  Page {currentPage} of {pages}
                </span>
              </PaginationItem>
              <PaginationItem>
                <Button
                  variant="outline"
                  disabled={currentPage === pages}
                  onClick={() => setPage(currentPage + 1)}
                >
                  Next
                </Button>
              </PaginationItem>
            </PaginationContent>
          </Pagination>
        )}
        <footer>
          <span>
            <i />
            {mode}
            {updated ? ` · Updated ${new Date(updated).toLocaleString()}` : ''}
          </span>
          <span>Duplicates checked by company and job ID or role link</span>
        </footer>
      </section>
      <div className="footnotes">
        <p>
          First seen on records the discovery channel. The employer application
          destination remains in Role link. Domains are approximate categories,
          and Date posted stays “Not stated” when no reliable publication date
          is available.
        </p>
        <p>
          {mode === 'Live on your Mac'
            ? 'Changes write to the original workbook. Close Excel before changing status, removing a role, or running the daily refresh.'
            : example
              ? 'The sample illustrates ranking evidence and the application pipeline.'
              : readOnly
                ? 'Application storage is not connected.'
                : 'Application progress is saved to your online tracker.'}{' '}
          {mailReady
            ? 'Email reminders run every 12 hours while an opening remains unapplied.'
            : ''}
        </p>
      </div>
      <JobDetails
        selected={selected}
        onClose={() => setSelected(null)}
        onPriorityChange={changePriority}
        savingId={rankingSavingId}
        readOnly={readOnly}
      />
    </main>
  );
}
