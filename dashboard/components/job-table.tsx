'use client';

import { ArrowUpRight, Trash2 } from 'lucide-react';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  effectiveTier,
  formatMatchScore,
  resumeLabel,
  type Job,
  STATUS_OPTIONS,
} from '@/lib/tracker';

type JobTableProps = {
  jobs: Job[];
  readOnly: boolean;
  savingId: string;
  local: boolean;
  onSelect: (job: Job) => void;
  onStatusChange: (job: Job, status: string) => Promise<void>;
  onRemove: (job: Job) => Promise<void>;
};

function tierClass(tier: string) {
  return tier ? tier.toLowerCase().replaceAll(' ', '-') : 'unranked';
}

export function JobTable({
  jobs,
  readOnly,
  savingId,
  local,
  onSelect,
  onStatusChange,
  onRemove,
}: JobTableProps) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Company / role</TableHead>
          <TableHead>Tier</TableHead>
          <TableHead>Match</TableHead>
          <TableHead>Confidence</TableHead>
          <TableHead>Best resume</TableHead>
          <TableHead>Domain</TableHead>
          <TableHead>Location</TableHead>
          <TableHead>Application</TableHead>
          <TableHead>Remove</TableHead>
          <TableHead>
            <span className="sr-only">Role details</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.map((job, index) => {
          const jobTier = effectiveTier(job);
          return (
            <TableRow key={job.id || job.url || index}>
              <TableCell>
                <button className="job-name" onClick={() => onSelect(job)}>
                  <span className="company-mark">
                    {job.company.slice(0, 2).toUpperCase()}
                  </span>
                  <span>
                    <b>{job.company}</b>
                    <span>{job.role}</span>
                  </span>
                </button>
              </TableCell>
              <TableCell>
                <span className={`badge tier-badge tier-${tierClass(jobTier)}`}>
                  {jobTier || 'Unranked'}
                </span>
              </TableCell>
              <TableCell>
                <span
                  className="match-score"
                  aria-label={`Match score ${formatMatchScore(job.match_score)}`}
                >
                  {formatMatchScore(job.match_score)}
                </span>
              </TableCell>
              <TableCell>
                <span className="badge confidence-badge">
                  {job.ranking_confidence || 'Unverified'}
                </span>
              </TableCell>
              <TableCell className="resume-cell">
                {resumeLabel(job.best_resume)}
              </TableCell>
              <TableCell>
                <span className="badge domain-badge">
                  {job.domain || 'Other'}
                </span>
              </TableCell>
              <TableCell className="location-cell">
                {job.location || 'Not stated'}
              </TableCell>
              <TableCell>
                <select
                  className="status-select"
                  aria-label={`Application status for ${job.role} at ${job.company}`}
                  value={job.status || 'Not applied'}
                  disabled={readOnly || !job.id || savingId === job.id}
                  onChange={(event) =>
                    void onStatusChange(job, event.target.value)
                  }
                >
                  {STATUS_OPTIONS.map((value) => (
                    <option key={value}>{value}</option>
                  ))}
                </select>
              </TableCell>
              <TableCell>
                <AlertDialog>
                  <AlertDialogTrigger
                    render={
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        disabled={readOnly || !job.id || savingId === job.id}
                        aria-label={`Remove ${job.role} at ${job.company}`}
                      />
                    }
                  >
                    <Trash2 size={16} />
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Remove this opening?</AlertDialogTitle>
                      <AlertDialogDescription>
                        {local
                          ? 'It will disappear, stay removed after daily refreshes, and stop generating reminders.'
                          : 'It will disappear and stay removed from your private online tracker.'}
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancel</AlertDialogCancel>
                      <AlertDialogAction onClick={() => void onRemove(job)}>
                        Remove
                      </AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </TableCell>
              <TableCell>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onSelect(job)}
                  aria-label={`View ${job.role} at ${job.company}`}
                >
                  <ArrowUpRight size={18} />
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
