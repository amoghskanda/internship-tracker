'use client';

import { ArrowUpRight } from 'lucide-react';
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet';
import {
  dateOnly,
  effectiveTier,
  formatMatchScore,
  resumeLabel,
  type Job,
  lines,
  normalizeTier,
  RANKING_TIER_OPTIONS,
  safeUrl,
  sourceLabel,
  words,
} from '@/lib/tracker';

function RankingList({
  title,
  value,
  empty,
}: {
  title: string;
  value: unknown;
  empty: string;
}) {
  const items = lines(value);
  return (
    <div className="ranking-list">
      <h4>{title}</h4>
      {items.length ? (
        <ul>
          {items.map((item, index) => (
            <li key={`${title}-${index}`}>{item}</li>
          ))}
        </ul>
      ) : (
        <p className="subtle">{empty}</p>
      )}
    </div>
  );
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
  return (
    tier ||
    (value === undefined || value === null || String(value).trim() === ''
      ? 'None'
      : String(value))
  );
}

type JobDetailsProps = {
  selected: Job | null;
  onClose: () => void;
  onPriorityChange: (job: Job, priority: string) => Promise<void>;
  savingId: string;
  readOnly: boolean;
};

export function JobDetails({
  selected,
  onClose,
  onPriorityChange,
  savingId,
  readOnly,
}: JobDetailsProps) {
  return (
    <Sheet open={Boolean(selected)} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="details">
        <SheetHeader>
          <SheetDescription>
            {selected?.company} · {selected?.location || 'Location not stated'}
          </SheetDescription>
          <SheetTitle>{selected?.role}</SheetTitle>
        </SheetHeader>
        {selected && (
          <div className="detail-body">
            <a
              className="download"
              href={safeUrl(selected.url)}
              target="_blank"
              rel="noreferrer"
            >
              Open role <ArrowUpRight size={17} />
            </a>
            <section
              className="ranking-panel"
              aria-labelledby="ranking-heading"
            >
              <div className="ranking-panel-heading">
                <h3 id="ranking-heading">Resume match</h3>
                <span
                  className={`badge tier-badge tier-${tierClass(effectiveTier(selected))}`}
                >
                  {effectiveTier(selected) || 'Unranked'}
                </span>
              </div>
              <dl className="ranking-meta">
                <div>
                  <dt>Match score</dt>
                  <dd>{formatMatchScore(selected.match_score)}</dd>
                </div>
                <div>
                  <dt>Confidence</dt>
                  <dd>{selected.ranking_confidence || 'Unverified'}</dd>
                </div>
                <div>
                  <dt>Best resume</dt>
                  <dd>{resumeLabel(selected.best_resume)}</dd>
                </div>
                <div>
                  <dt>Eligibility</dt>
                  <dd>{selected.eligibility || 'Not evaluated'}</dd>
                </div>
                <div>
                  <dt>Manual override</dt>
                  <dd>{manualOverride(selected.manual_priority_override)}</dd>
                </div>
              </dl>
              <label className="ranking-override" htmlFor="manual-priority">
                <span>Manual priority override</span>
                <select
                  id="manual-priority"
                  value={normalizeTier(selected.manual_priority_override)}
                  disabled={
                    readOnly || !selected.id || savingId === selected.id
                  }
                  onChange={(event) =>
                    void onPriorityChange(selected, event.target.value)
                  }
                >
                  <option value="">Automatic rank</option>
                  {RANKING_TIER_OPTIONS.filter(
                    (value) => value !== 'All tiers' && value !== 'Ineligible',
                  ).map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
              <h4>Why this rank</h4>
              <p>
                {selected.ranking_explanation ||
                  'The ranker has not added an explanation yet.'}
              </p>
              {selected.ranking_confidence_reason && (
                <p className="subtle">{selected.ranking_confidence_reason}</p>
              )}
              <RankingList
                title="Strong matches"
                value={selected.strong_matches}
                empty="No matching evidence has been recorded yet."
              />
              <RankingList
                title="Missing requirements"
                value={selected.missing_requirements}
                empty="No missing requirements have been recorded."
              />
              <RankingList
                title="Tailoring suggestions"
                value={selected.tailoring_suggestions}
                empty="No tailoring suggestions have been recorded."
              />
              <dl className="ranking-meta ranking-meta-footer">
                <div>
                  <dt>Resume version</dt>
                  <dd>{selected.resume_version || 'Not recorded'}</dd>
                </div>
                <div>
                  <dt>Scoring version</dt>
                  <dd>{selected.scoring_version || 'Not recorded'}</dd>
                </div>
                <div>
                  <dt>Last scored</dt>
                  <dd>{scoredAt(selected.last_scored)}</dd>
                </div>
              </dl>
            </section>
            <h3>Domain</h3>
            <p>{selected.domain || 'Other'}</p>
            <h3>First seen on</h3>
            <p>{sourceLabel(selected.source)}</p>
            <h3>Date posted</h3>
            <p>{dateOnly(selected.date_posted)}</p>
            <h3>Job description</h3>
            <p>
              {selected.jd ||
                'Description has not been retrieved. Read the employer listing for complete requirements.'}
            </p>
            <h3>Skills needed</h3>
            <p>
              {words(selected.skills) || 'Not stated in the collected listing.'}
            </p>
            <h3>Visa sponsorship</h3>
            <p>{selected.visa_sponsorship || 'not stated'}</p>
            <p className="subtle">
              {selected.visa_evidence ||
                'No explicit sponsorship statement collected.'}
            </p>
            <h3>LinkedIn contacts</h3>
            <p>
              {words(selected.linkedin_contacts) ||
                'Not verified. Add confirmed names in Excel.'}
            </p>
            <h3>Your application</h3>
            <p>
              {selected.status || 'Not applied'}
              {selected.applied_date ? ` · ${selected.applied_date}` : ''}
            </p>
            <p>{selected.notes || 'No notes yet.'}</p>
            <h3>Listing record</h3>
            <p>Job ID: {selected.job_id || 'Not stated'}</p>
            <p>Discovered: {dateOnly(selected.discovered_at)}</p>
            {safeUrl(selected.source_url) && (
              <a
                href={safeUrl(selected.source_url)}
                target="_blank"
                rel="noreferrer"
              >
                View discovery page
              </a>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
