'use client';
/* oxlint-disable next/no-html-link-for-pages -- native navigation is required for the hosted Vinext route. */

import { useEffect, useState } from 'react';
import { ArrowUpRight, BriefcaseBusiness, FileSpreadsheet, RefreshCw, Search, Trash2 } from 'lucide-react';
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Pagination, PaginationContent, PaginationItem } from '@/components/ui/pagination';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { ACTIVE_APPLICATION_STATUSES, dateOnly, effectiveTier, formatMatchScore, isRemoved, Job, lines, loadTracker, normalizeTier, RANKING_TIER_OPTIONS, safeUrl, saveApplication, scoreValue, sourceLabel, STATUS_OPTIONS, tierRank, words } from '@/lib/tracker';

function RankingList({ title, value, empty }: { title: string; value: unknown; empty: string }) {
  const items = lines(value);
  return <div className="ranking-list"><h4>{title}</h4>{items.length ? <ul>{items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}</ul> : <p className="subtle">{empty}</p>}</div>;
}

function tierClass(tier: string) {
  return tier ? tier.toLowerCase().replaceAll(' ', '-') : 'unranked';
}

function scoredAt(value?: string) {
  if (!value) return 'Not scored';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function manualOverride(value: Job['manual_priority_override']) {
  const tier = normalizeTier(value);
  return tier || (value === undefined || value === null || String(value).trim() === '' ? 'None' : String(value));
}

export default function Home() {
  const [jobs, setJobs] = useState<Job[]>([]), [query, setQuery] = useState(''), [view, setView] = useState('All roles');
  const [domain, setDomain] = useState('All domains'), [source, setSource] = useState('All sources'), [tier, setTier] = useState('All tiers');
  const [selected, setSelected] = useState<Job | null>(null), [mode, setMode] = useState('Loading'), [updated, setUpdated] = useState(''), [error, setError] = useState('');
  const [mailReady, setMailReady] = useState(false), [savingId, setSavingId] = useState(''), [rankingSavingId, setRankingSavingId] = useState(''), [page, setPage] = useState(1);

  async function refresh() {
    try {
      const result = await loadTracker();
      setJobs(result.jobs); setUpdated(result.updated); setMode(result.local ? 'Live on your Mac' : 'Synced online'); setError('');
      if (result.local) { try { const response = await fetch('/api/status', { cache: 'no-store' }); if (response.ok) { const status = await response.json() as { email_configured?: boolean }; setMailReady(Boolean(status.email_configured)); } } catch {} }
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Refresh failed.'); }
  }

  async function changeStatus(job: Job, status: string) {
    if (!job.id) return;
    setSavingId(job.id); setError('');
    try {
      const appliedDate = status === 'Not applied' ? '' : job.applied_date || new Date().toISOString().slice(0, 10);
      await saveApplication(job.id, { status, applied_date: appliedDate });
      setJobs(rows => rows.map(row => row.id === job.id ? { ...row, status, applied_date: appliedDate } : row));
      if (status === 'Applied') window.location.assign(`/applications?job=${encodeURIComponent(job.id)}`);
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Status could not be saved.'); }
    finally { setSavingId(''); }
  }

  async function removeJob(job: Job) {
    if (!job.id) return;
    setSavingId(job.id); setError('');
    try { await saveApplication(job.id, {}, 'DELETE'); setJobs(rows => rows.filter(row => row.id !== job.id)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Opening could not be removed.'); }
    finally { setSavingId(''); }
  }

  async function changePriority(job: Job, override: string) {
    if (!job.id) return;
    setRankingSavingId(job.id); setError('');
    try {
      await saveApplication(job.id, { manual_priority_override: override });
      setJobs(rows => rows.map(row => row.id === job.id ? { ...row, manual_priority_override: override } : row));
      setSelected(row => {
        if (!row || row.id !== job.id) return row;
        return { ...row, manual_priority_override: override };
      });
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Priority override could not be saved.'); }
    finally { setRankingSavingId(''); }
  }

  useEffect(() => { const initial = window.setTimeout(() => void refresh(), 0); const timer = window.setInterval(refresh, 60000); return () => { clearTimeout(initial); clearInterval(timer); }; }, []);
  const activeJobs = jobs.filter(job => !isRemoved(job));
  const pending = activeJobs.filter(job => !job.applied_date && !ACTIVE_APPLICATION_STATUSES.has(job.status || 'Not applied'));
  const applied = activeJobs.filter(job => Boolean(job.applied_date) || ACTIVE_APPLICATION_STATUSES.has(job.status || ''));
  const domains = [...new Set(activeJobs.map(job => job.domain).filter((value): value is string => Boolean(value)))].sort();
  const sources = [...new Set(activeJobs.map(job => sourceLabel(job.source)))].sort();
  const filtered = activeJobs.filter(job =>
    (view !== 'Not applied' || pending.includes(job)) && (view !== 'Applied' || applied.includes(job)) &&
    (view !== 'Sponsorship provided' || job.visa_sponsorship === 'provided') &&
    (domain === 'All domains' || job.domain === domain) && (source === 'All sources' || sourceLabel(job.source) === source) &&
    (tier === 'All tiers' || effectiveTier(job) === tier) &&
    `${job.company} ${job.role} ${job.domain} ${job.location} ${words(job.skills)} ${sourceLabel(job.source)} ${job.best_resume || ''} ${words(job.strong_matches)} ${words(job.missing_requirements)}`.toLowerCase().includes(query.toLowerCase())).sort((first, second) => {
      const tierDifference = tierRank(effectiveTier(first)) - tierRank(effectiveTier(second));
      if (tierDifference) return tierDifference;
      const scoreDifference = (scoreValue(second.match_score) ?? -Infinity) - (scoreValue(first.match_score) ?? -Infinity);
      if (scoreDifference) return scoreDifference;
      return `${first.company} ${first.role}`.localeCompare(`${second.company} ${second.role}`);
    });
  const pages = Math.max(1, Math.ceil(filtered.length / 50)), currentPage = Math.min(page, pages);
  const visible = filtered.slice((currentPage - 1) * 50, currentPage * 50);

  return <main className="tracker">
    <header className="masthead"><div className="brand"><BriefcaseBusiness size={22}/><span>Internship desk</span></div><span className="season">SUMMER / 2027</span><a className="owner" href="/applications">Application pipeline</a></header>
    <section className="heading"><div><p className="eyebrow">APPLICATION TRACKER</p><h1>Applications, in view.</h1><p className="intro">Your summer 2027 opportunities.</p></div><div className="heading-actions"><a className="secondary-action" href="/applications">Track applied roles</a><a className="download" href={mode === 'Live on your Mac' ? '/api/workbook' : '/Summer-2027-Internships.xlsx'} download><FileSpreadsheet size={19}/> Download Excel <ArrowUpRight size={17}/></a></div></section>
    <section className="metrics" aria-label="Application summary"><div><span>Tracked openings</span><strong>{activeJobs.length.toLocaleString()}</strong><small>Summer 2027</small></div><div><span>Ready to apply</span><strong>{pending.length.toLocaleString()}</strong><small>Not applied yet</small></div><div><span>Applications sent</span><strong>{applied.length.toLocaleString()}</strong><small><a href="/applications">View pipeline</a></small></div><div className="schedule"><span>Daily search</span><strong>7:00<span>am</span></strong><small>Pacific time · Mac must be awake</small></div></section>
    <section className="workspace"><div className="workspace-head"><div><h2>Your opportunities <span>{filtered.length}</span></h2><p>Sorted by application tier and match score. Status changes save immediately.</p></div><Button variant="outline" onClick={refresh}><RefreshCw size={15}/> Refresh</Button></div>
      <div className="controls"><nav aria-label="Filter applications">{['All roles', 'Not applied', 'Applied', 'Sponsorship provided'].map(value => <button key={value} aria-pressed={view === value} className={view === value ? 'active' : ''} onClick={() => { setView(value); setPage(1); }}>{value}</button>)}</nav><div className="control-fields"><label className="domain-filter" htmlFor="tier-filter"><span>Tier</span><select id="tier-filter" value={tier} onChange={event => { setTier(event.target.value); setPage(1); }}>{RANKING_TIER_OPTIONS.map(value => <option key={value}>{value}</option>)}</select></label><label className="domain-filter" htmlFor="domain-filter"><span>Domain</span><select id="domain-filter" value={domain} onChange={event => { setDomain(event.target.value); setPage(1); }}><option>All domains</option>{domains.map(value => <option key={value}>{value}</option>)}</select></label><label className="domain-filter" htmlFor="source-filter"><span>Source</span><select id="source-filter" value={source} onChange={event => { setSource(event.target.value); setPage(1); }}><option>All sources</option>{sources.map(value => <option key={value}>{value}</option>)}</select></label><div className="search"><Search size={17}/><Input aria-label="Search roles, companies, domains, sources, skills or resumes" value={query} onChange={event => { setQuery(event.target.value); setPage(1); }} placeholder="Search roles, companies, skills"/></div></div></div>
      {error && <p role="alert" className="notice">{error}</p>}
      <Table><TableHeader><TableRow><TableHead>Company / role</TableHead><TableHead>Tier</TableHead><TableHead>Match</TableHead><TableHead>Confidence</TableHead><TableHead>Best resume</TableHead><TableHead>Domain</TableHead><TableHead>Location</TableHead><TableHead>Date posted</TableHead><TableHead>First seen on</TableHead><TableHead>Visa sponsorship</TableHead><TableHead>Application</TableHead><TableHead>Contacts</TableHead><TableHead>Remove</TableHead><TableHead><span className="sr-only">Role details</span></TableHead></TableRow></TableHeader><TableBody>{visible.map((job, index) => { const jobTier = effectiveTier(job); return <TableRow key={job.id || job.url || index}><TableCell><button className="job-name" onClick={() => setSelected(job)}><span className="company-mark">{job.company.slice(0, 2).toUpperCase()}</span><span><b>{job.company}</b><span>{job.role}</span></span></button></TableCell><TableCell><span className={`badge tier-badge tier-${tierClass(jobTier)}`}>{jobTier || 'Unranked'}</span></TableCell><TableCell><span className="match-score" aria-label={`Match score ${formatMatchScore(job.match_score)}`}>{formatMatchScore(job.match_score)}</span></TableCell><TableCell><span className="badge confidence-badge">{job.ranking_confidence || 'Unverified'}</span></TableCell><TableCell className="resume-cell">{job.best_resume || 'Not selected'}</TableCell><TableCell><span className="badge domain-badge">{job.domain || 'Other'}</span></TableCell><TableCell>{job.location || 'Not stated'}</TableCell><TableCell>{dateOnly(job.date_posted)}</TableCell><TableCell>{sourceLabel(job.source)}</TableCell><TableCell><span className={`badge visa-${(job.visa_sponsorship || 'not stated').replaceAll(' ', '-')}`}>{job.visa_sponsorship || 'not stated'}</span></TableCell><TableCell><select className="status-select" aria-label={`Application status for ${job.role} at ${job.company}`} value={job.status || 'Not applied'} disabled={!job.id || savingId === job.id} onChange={event => void changeStatus(job, event.target.value)}>{STATUS_OPTIONS.map(value => <option key={value}>{value}</option>)}</select></TableCell><TableCell className="contacts">{words(job.linkedin_contacts) || 'Not verified'}</TableCell><TableCell><AlertDialog><AlertDialogTrigger render={<Button variant="ghost" size="icon-sm" aria-label={`Remove ${job.role} at ${job.company}`}/> }><Trash2 size={16}/></AlertDialogTrigger><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>Remove this opening?</AlertDialogTitle><AlertDialogDescription>{mode === 'Live on your Mac' ? 'It will disappear, stay removed after daily refreshes, and stop generating reminders.' : 'It will disappear and stay removed from your private online tracker.'}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>Cancel</AlertDialogCancel><AlertDialogAction onClick={() => void removeJob(job)}>Remove</AlertDialogAction></AlertDialogFooter></AlertDialogContent></AlertDialog></TableCell><TableCell><Button variant="ghost" size="sm" onClick={() => setSelected(job)} aria-label={`View ${job.role} at ${job.company}`}><ArrowUpRight size={18}/></Button></TableCell></TableRow>; })}</TableBody></Table>
      {!filtered.length && <div className="empty"><h3>{activeJobs.length ? 'No matching openings' : 'Waiting for the first search'}</h3><p>{activeJobs.length ? 'Try another tier, company, role, source, or skill.' : 'Verified summer 2027 openings will appear here after collection.'}</p></div>}
      {filtered.length > 50 && <Pagination className="page-controls"><PaginationContent><PaginationItem><Button variant="outline" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}>Previous</Button></PaginationItem><PaginationItem><span className="page-count">Page {currentPage} of {pages}</span></PaginationItem><PaginationItem><Button variant="outline" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}>Next</Button></PaginationItem></PaginationContent></Pagination>}
      <footer><span><i/>{mode}{updated ? ` · Updated ${new Date(updated).toLocaleString()}` : ''}</span><span>Duplicates checked by company and job ID or role link</span></footer>
    </section>
    <div className="footnotes"><p>First seen on records the discovery channel. The employer application destination remains in Role link. Domains are approximate categories, and Date posted stays “Not stated” when no reliable publication date is available.</p><p>{mode === 'Live on your Mac' ? 'Changes write to the original workbook. Close Excel before changing status, removing a role, or running the daily refresh.' : 'Application progress is saved to your private online tracker.'} {mailReady ? 'Email reminders run every 12 hours while an opening remains unapplied.' : ''}</p></div>
    <Sheet open={Boolean(selected)} onOpenChange={open => !open && setSelected(null)}><SheetContent className="details"><SheetHeader><SheetDescription>{selected?.company} · {selected?.location || 'Location not stated'}</SheetDescription><SheetTitle>{selected?.role}</SheetTitle></SheetHeader>{selected && <div className="detail-body"><a className="download" href={safeUrl(selected.url)} target="_blank" rel="noreferrer">Open role <ArrowUpRight size={17}/></a><section className="ranking-panel" aria-labelledby="ranking-heading"><div className="ranking-panel-heading"><h3 id="ranking-heading">Resume match</h3><span className={`badge tier-badge tier-${tierClass(effectiveTier(selected))}`}>{effectiveTier(selected) || 'Unranked'}</span></div><dl className="ranking-meta"><div><dt>Match score</dt><dd>{formatMatchScore(selected.match_score)}</dd></div><div><dt>Confidence</dt><dd>{selected.ranking_confidence || 'Unverified'}</dd></div><div><dt>Best resume</dt><dd>{selected.best_resume || 'Not selected'}</dd></div><div><dt>Eligibility</dt><dd>{selected.eligibility || 'Not evaluated'}</dd></div><div><dt>Manual override</dt><dd>{manualOverride(selected.manual_priority_override)}</dd></div></dl><label className="ranking-override" htmlFor="manual-priority"><span>Manual priority override</span><select id="manual-priority" value={normalizeTier(selected.manual_priority_override)} disabled={!selected.id || rankingSavingId === selected.id} onChange={event => void changePriority(selected, event.target.value)}><option value="">Automatic rank</option>{RANKING_TIER_OPTIONS.filter(value => value !== 'All tiers' && value !== 'Ineligible').map(value => <option key={value} value={value}>{value}</option>)}</select></label><h4>Why this rank</h4><p>{selected.ranking_explanation || 'The ranker has not added an explanation yet.'}</p>{selected.ranking_confidence_reason && <p className="subtle">{selected.ranking_confidence_reason}</p>}<RankingList title="Strong matches" value={selected.strong_matches} empty="No matching evidence has been recorded yet."/><RankingList title="Missing requirements" value={selected.missing_requirements} empty="No missing requirements have been recorded."/><RankingList title="Tailoring suggestions" value={selected.tailoring_suggestions} empty="No tailoring suggestions have been recorded."/><dl className="ranking-meta ranking-meta-footer"><div><dt>Resume version</dt><dd>{selected.resume_version || 'Not recorded'}</dd></div><div><dt>Scoring version</dt><dd>{selected.scoring_version || 'Not recorded'}</dd></div><div><dt>Last scored</dt><dd>{scoredAt(selected.last_scored)}</dd></div></dl></section><h3>Domain</h3><p>{selected.domain || 'Other'}</p><h3>First seen on</h3><p>{sourceLabel(selected.source)}</p><h3>Date posted</h3><p>{dateOnly(selected.date_posted)}</p><h3>Job description</h3><p>{selected.jd || 'Description has not been retrieved. Read the employer listing for complete requirements.'}</p><h3>Skills needed</h3><p>{words(selected.skills) || 'Not stated in the collected listing.'}</p><h3>Visa sponsorship</h3><p>{selected.visa_sponsorship || 'not stated'}</p><p className="subtle">{selected.visa_evidence || 'No explicit sponsorship statement collected.'}</p><h3>LinkedIn contacts</h3><p>{words(selected.linkedin_contacts) || 'Not verified. Add confirmed names in Excel.'}</p><h3>Your application</h3><p>{selected.status || 'Not applied'}{selected.applied_date ? ` · ${selected.applied_date}` : ''}</p><p>{selected.notes || 'No notes yet.'}</p><h3>Listing record</h3><p>Job ID: {selected.job_id || 'Not stated'}</p><p>Discovered: {dateOnly(selected.discovered_at)}</p>{safeUrl(selected.source_url) && <a href={safeUrl(selected.source_url)} target="_blank" rel="noreferrer">View discovery page</a>}</div>}</SheetContent></Sheet>
  </main>;
}
