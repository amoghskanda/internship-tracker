#!/usr/bin/env node

import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

export const SOURCE_FIELDS = [
  "company",
  "role",
  "domain",
  "url",
  "job_id",
  "location",
  "jd",
  "skills",
  "visa_sponsorship",
  "visa_evidence",
  "source_url",
  "source",
  "date_posted",
  "discovered_at",
  "last_seen",
  "season",
  "agent_tier",
  "match_score",
  "best_resume",
  "eligibility",
  "ranking_confidence",
  "ranking_confidence_reason",
  "strong_matches",
  "missing_requirements",
  "tailoring_suggestions",
  "ranking_explanation",
  "resume_version",
  "scoring_version",
  "last_scored",
];

export const MANUAL_FIELDS = [
  "status",
  "applied_date",
  "deadline",
  "oa_date",
  "interview_date",
  "notes",
  "linkedin_contacts",
  "manual_priority_override",
  "removed",
];

// Keep the editable application columns near the left edge of a fresh tracker.
// The stable id is intentionally last so the sheet reads like a tracker while
// the website still gets every canonical field in the JSON sidecar.
export const ALL_FIELDS = [
  "company",
  "role",
  "domain",
  "agent_tier",
  "match_score",
  "best_resume",
  "eligibility",
  "ranking_confidence",
  "ranking_confidence_reason",
  "manual_priority_override",
  "status",
  "applied_date",
  "deadline",
  "oa_date",
  "interview_date",
  "notes",
  "linkedin_contacts",
  "removed",
  "url",
  "job_id",
  "location",
  "jd",
  "skills",
  "visa_sponsorship",
  "visa_evidence",
  "source_url",
  "source",
  "date_posted",
  "discovered_at",
  "last_seen",
  "season",
  "strong_matches",
  "missing_requirements",
  "tailoring_suggestions",
  "ranking_explanation",
  "resume_version",
  "scoring_version",
  "last_scored",
  "id",
];

const OUTPUT_HEADER_LABELS = {
  company: "Company",
  role: "Role",
  domain: "Domain",
  agent_tier: "Agent tier",
  match_score: "Match score",
  best_resume: "Best resume",
  eligibility: "Eligibility",
  ranking_confidence: "Ranking confidence",
  ranking_confidence_reason: "Ranking confidence reason",
  manual_priority_override: "Priority override",
  status: "Status",
  applied_date: "Applied date",
  deadline: "Application deadline",
  oa_date: "OA date",
  interview_date: "Interview date",
  notes: "Notes",
  linkedin_contacts: "LinkedIn contacts",
  removed: "Removed",
  url: "Role link",
  job_id: "Job ID",
  location: "Location",
  jd: "JD",
  skills: "Skills needed",
  visa_sponsorship: "Visa sponsorship",
  visa_evidence: "Visa evidence",
  source_url: "Source URL",
  source: "Source",
  date_posted: "Date posted",
  discovered_at: "Discovered at",
  last_seen: "Last seen",
  season: "Season",
  strong_matches: "Strong matches",
  missing_requirements: "Missing requirements",
  tailoring_suggestions: "Tailoring suggestions",
  ranking_explanation: "Ranking explanation",
  resume_version: "Resume version",
  scoring_version: "Scoring version",
  last_scored: "Last scored",
  id: "Stable ID",
};

export const TIER_VALUES = ["", "Tier 1", "Tier 2", "Tier 3", "Tier 4"];

export const STATUS_VALUES = [
  "Not applied",
  "Interested",
  "Applied",
  "OA",
  "Interviewing",
  "Offer",
  "Rejected",
  "Withdrawn",
];

const DATE_FIELDS = new Set(["date_posted", "discovered_at", "last_seen", "applied_date", "deadline", "oa_date", "interview_date", "last_scored"]);

const FIELD_ALIASES = {
  id: ["id", "stable_id", "stable id", "stableid", "stable key", "stable_key"],
  company: ["company", "employer", "company_name", "company name"],
  role: ["role", "title", "job title", "position"],
  domain: ["domain", "job domain", "role domain", "category"],
  agent_tier: ["agent_tier", "agent tier", "tier", "rank tier"],
  match_score: ["match_score", "match score", "fit score", "ranking score"],
  best_resume: ["best_resume", "best resume", "recommended resume"],
  eligibility: ["eligibility", "eligible", "eligibility status"],
  ranking_confidence: ["ranking_confidence", "ranking confidence", "match confidence"],
  ranking_confidence_reason: ["ranking_confidence_reason", "ranking confidence reason", "confidence reason"],
  manual_priority_override: ["manual_priority_override", "manual priority override", "priority override", "tier override"],
  url: ["url", "job_url", "job url", "listing_url", "listing url"],
  job_id: ["job_id", "job id", "jobid", "requisition_id", "requisition id", "req_id"],
  location: ["location", "locations"],
  jd: ["jd", "job_description", "job description", "description"],
  skills: ["skills", "skill", "required_skills", "required skills"],
  visa_sponsorship: [
    "visa_sponsorship",
    "visa sponsorship",
    "visa",
    "sponsorship",
  ],
  visa_evidence: ["visa_evidence", "visa evidence", "sponsorship_evidence"],
  source_url: ["source_url", "source url"],
  source: ["source", "source_name", "source name", "feed", "feed source"],
  date_posted: [
    "date_posted",
    "date posted",
    "datePosted",
    "posted",
    "posted date",
    "posting date",
    "published_at",
    "published at",
    "first_published",
    "first published",
    "publish_time",
    "publish time",
    "publishTime",
  ],
  discovered_at: ["discovered_at", "discovered at", "discovered", "date discovered"],
  last_seen: ["last_seen", "last seen", "updated_at", "updated at"],
  season: ["season", "recruiting_season", "recruiting season"],
  strong_matches: ["strong_matches", "strong matches", "matched evidence"],
  missing_requirements: ["missing_requirements", "missing requirements", "gaps"],
  tailoring_suggestions: ["tailoring_suggestions", "tailoring suggestions", "tailoring"],
  ranking_explanation: ["ranking_explanation", "ranking explanation", "match explanation"],
  resume_version: ["resume_version", "resume version"],
  scoring_version: ["scoring_version", "scoring version"],
  last_scored: ["last_scored", "last scored", "scored at"],
  status: ["status", "application_status", "application status"],
  applied_date: ["applied_date", "applied date", "date_applied", "date applied"],
  deadline: ["deadline", "application_deadline", "application deadline", "due date"],
  oa_date: ["oa_date", "oa date", "online assessment date", "assessment date"],
  interview_date: ["interview_date", "interview date", "next interview", "interview"],
  notes: ["notes", "note", "application_notes", "application notes"],
  linkedin_contacts: [
    "linkedin_contacts",
    "linkedin contacts",
    "linkedin_contact",
    "linkedin contact",
    "contacts",
  ],
  removed: ["removed", "hidden", "archived"],
};

const ALIAS_TO_FIELD = new Map();
for (const [field, aliases] of Object.entries(FIELD_ALIASES)) {
  for (const alias of aliases) ALIAS_TO_FIELD.set(normalizeHeader(alias), field);
}
// Fresh trackers use human-facing labels. Treat those labels as canonical
// aliases everywhere (reading, merging, and deciding whether a new column is
// missing) so a second sync never creates `Role link_2`/`Skills needed_2`.
for (const [field, label] of Object.entries(OUTPUT_HEADER_LABELS)) {
  ALIAS_TO_FIELD.set(normalizeHeader(label), field);
}

export class SyncError extends Error {
  constructor(message, code = "SYNC_ERROR") {
    super(message);
    this.name = "SyncError";
    this.code = code;
  }
}

export class ConcurrentWorkbookEditError extends SyncError {
  constructor(message) {
    super(message, "CONCURRENT_EDIT");
    this.name = "ConcurrentWorkbookEditError";
  }
}

export function normalizeHeader(value) {
  return String(value ?? "")
    .trim()
    .toLowerCase()
    .replace(/[\u2010-\u2015]/g, "-")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
}

function isEmptyValue(value) {
  return value === undefined || value === null || (typeof value === "string" && value.trim() === "");
}

function displayValue(value) {
  if (value === undefined || value === null) return "";
  if (value instanceof Date) return value.toISOString().slice(0, 10);
  if (Array.isArray(value)) return value.map((item) => displayValue(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

const SOURCE_LABELS = {
  ashby: "Ashby",
  greenhouse: "Greenhouse",
  instagram: "Instagram",
  jobright: "Jobright",
  lever: "Lever",
  linkedin: "LinkedIn",
  simplify: "Simplify",
  workday: "Workday",
};

function titleCaseSource(value) {
  return value
    .replace(/[\s_-]+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

/** Convert feed identifiers such as greenhouse:scaleai,simplify to labels. */
export function humanizeSource(value) {
  const raw = displayValue(value).trim();
  if (!raw) return "";
  const labels = [];
  for (const part of raw.split(",")) {
    const prefix = part.trim().split(":", 1)[0].trim().toLowerCase();
    if (!prefix) continue;
    const label = SOURCE_LABELS[prefix] ?? titleCaseSource(prefix);
    if (label && !labels.includes(label)) labels.push(label);
  }
  return labels.join(", ");
}

function normalizedText(value) {
  const output = displayValue(value);
  if (typeof output === "string") return output.trim();
  return output;
}

function hasContent(row) {
  return row.some((value) => !isEmptyValue(value));
}

function dateToJson(value) {
  const preserveTimestamp = (date) => {
    const iso = date.toISOString();
    return iso.endsWith("T00:00:00.000Z") ? iso.slice(0, 10) : iso;
  };
  if (value instanceof Date) return preserveTimestamp(value);
  if (typeof value === "number" && Number.isFinite(value)) {
    // Artifact Tool can expose imported Excel dates as serial numbers. Excel's
    // 1900 date system uses 1899-12-30 as its practical epoch.
    const millis = Date.UTC(1899, 11, 30) + value * 86_400_000;
    const date = new Date(millis);
    if (!Number.isNaN(date.valueOf())) return preserveTimestamp(date);
  }
  if (typeof value === "string") return value.trim();
  return displayValue(value);
}

function jsonValue(value, field) {
  if (field === "source") {
    const labels = humanizeSource(value).split(",").map((label) => label.trim()).filter(Boolean);
    // Historical combined values came from a collector that ran Simplify first
    // and later replaced the preferred record with richer employer data.
    if (labels.includes("Simplify")) return "Simplify";
    return labels[0] ?? "";
  }
  if (DATE_FIELDS.has(field)) return dateToJson(value);
  if (value === undefined || value === null) return "";
  if (Array.isArray(value)) return value.map((item) => displayValue(item)).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return value;
}

function isDateLike(value) {
  if (value instanceof Date) return true;
  if (typeof value !== "string") return false;
  const trimmed = value.trim();
  return /^\d{4}-\d{2}-\d{2}(?:[T\s].*)?$/.test(trimmed);
}

function workbookValue(value, field) {
  if (value === undefined || value === null || value === "") return "";
  if (DATE_FIELDS.has(field) && isDateLike(value)) {
    const date = value instanceof Date ? value : new Date(value);
    if (!Number.isNaN(date.valueOf())) return date;
  }
  return displayValue(value);
}

function stableUrlId(url) {
  let normalized = String(url).trim();
  try {
    const parsed = new URL(normalized);
    parsed.protocol = parsed.protocol.toLowerCase();
    parsed.hostname = parsed.hostname.toLowerCase();
    parsed.hash = "";
    parsed.pathname = parsed.pathname.replace(/\/+$/, "") || "/";
    normalized = parsed.toString();
  } catch {
    normalized = normalized.toLowerCase().replace(/\/+$/, "");
  }
  const digest = crypto.createHash("sha256").update(normalized).digest("hex").slice(0, 20);
  return `url:${digest}`;
}

function stablePart(value) {
  return String(value)
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ")
    .replace(/[|:]+/g, " ");
}

export function deriveStableId(job, context = "job") {
  const direct = job.id ?? job.stable_id ?? job.stableId ?? job["stable id"];
  if (!isEmptyValue(direct)) return String(direct).trim();

  const jobId = job.job_id ?? job.jobId ?? job.jobID;
  if (!isEmptyValue(jobId)) {
    const company = job.company ?? job.employer ?? job.company_name;
    return company && !isEmptyValue(company)
      ? `company:${stablePart(company)}|job:${stablePart(jobId)}`
      : `job:${stablePart(jobId)}`;
  }

  const url = job.url ?? job.job_url ?? job.jobUrl ?? job.listing_url;
  if (!isEmptyValue(url)) return stableUrlId(url);

  throw new SyncError(
    `${context} has no stable id, job_id, or url. Add one of those fields so records can be merged safely.`,
    "MISSING_STABLE_ID",
  );
}

function aliasedValue(record, field) {
  if (Object.prototype.hasOwnProperty.call(record, field)) return record[field];
  for (const alias of FIELD_ALIASES[field] ?? []) {
    if (Object.prototype.hasOwnProperty.call(record, alias)) return record[alias];
  }
  return undefined;
}

export function normalizeJob(record, context = "job") {
  if (!record || typeof record !== "object" || Array.isArray(record)) {
    throw new SyncError(`${context} must be an object`, "INVALID_JOB");
  }

  const id = deriveStableId(record, context);
  const normalized = { id };
  for (const field of SOURCE_FIELDS) {
    normalized[field] = jsonValue(aliasedValue(record, field), field);
  }
  for (const field of MANUAL_FIELDS) {
    normalized[field] = jsonValue(aliasedValue(record, field), field);
  }
  return normalized;
}

export function normalizeJobsDocument(document) {
  const jobs = Array.isArray(document) ? document : document?.jobs ?? document?.records;
  if (!Array.isArray(jobs)) {
    throw new SyncError("Jobs JSON must be an array or an object with a jobs or records array", "INVALID_JOBS_JSON");
  }
  const normalized = jobs.map((job, index) => normalizeJob(job, `jobs[${index}]`));
  assertUniqueIds(normalized, "jobs JSON");
  return normalized;
}

export function assertUniqueIds(rows, label) {
  const seen = new Map();
  for (const [index, row] of rows.entries()) {
    const id = String(row.id ?? "").trim();
    if (!id) throw new SyncError(`${label} row ${index + 1} has an empty stable id`, "MISSING_STABLE_ID");
    const previous = seen.get(id);
    if (previous !== undefined) {
      throw new SyncError(`${label} contains duplicate stable id "${id}" at rows ${previous + 1} and ${index + 1}`, "DUPLICATE_STABLE_ID");
    }
    seen.set(id, index);
  }
}

function emptyManualFields() {
  return {
    status: "Not applied",
    applied_date: "",
    deadline: "",
    oa_date: "",
    interview_date: "",
    notes: "",
    linkedin_contacts: "",
    manual_priority_override: "",
    removed: "No",
  };
}

function emptySourceFields() {
  return Object.fromEntries(SOURCE_FIELDS.map((field) => [field, ""]));
}

function cloneRow(row) {
  return { ...row, _extra: { ...(row._extra ?? {}) } };
}

export function mergeJobs(existingRows, incomingRows) {
  assertUniqueIds(existingRows, "existing workbook");
  assertUniqueIds(incomingRows, "jobs JSON");

  const merged = existingRows.map((row) => {
    const output = cloneRow(row);
    for (const field of SOURCE_FIELDS) output[field] = jsonValue(output[field], field);
    for (const field of MANUAL_FIELDS) output[field] = jsonValue(output[field], field);
    if (isEmptyValue(output.status)) output.status = "Not applied";
    for (const field of MANUAL_FIELDS) if (output[field] === undefined || output[field] === null) output[field] = "";
    return output;
  });

  const byId = new Map(merged.map((row, index) => [String(row.id), index]));
  for (const incoming of incomingRows) {
    const id = String(incoming.id);
    const existingIndex = byId.get(id);
    if (existingIndex === undefined) {
      const newRow = { id, ...emptySourceFields(), ...emptyManualFields(), _extra: {} };
      for (const field of SOURCE_FIELDS) {
        if (!isEmptyValue(incoming[field])) newRow[field] = incoming[field];
      }
      for (const field of MANUAL_FIELDS) {
        if (!isEmptyValue(incoming[field])) newRow[field] = incoming[field];
      }
      merged.push(newRow);
      byId.set(id, merged.length - 1);
      continue;
    }

    const existing = merged[existingIndex];
    for (const field of SOURCE_FIELDS) {
      // The first-seen date is part of a job's history. Keep it once set;
      // recurring feeds may refresh last_seen without resetting discovery age.
      if (field === "discovered_at" && !isEmptyValue(existing[field])) continue;
      // Source is the first discovery channel. Keep it once recorded.
      if (field === "source" && !isEmptyValue(existing[field])) continue;
      if (!isEmptyValue(incoming[field])) existing[field] = incoming[field];
    }
    // Manual columns belong to the workbook. Incoming manual values never replace an
    // existing workbook value, including a deliberate zero or blank note.
    if (isEmptyValue(existing.status)) existing.status = "Not applied";
    for (const field of MANUAL_FIELDS) if (existing[field] === undefined || existing[field] === null) existing[field] = "";
  }

  return merged;
}

function findHeaderRow(values) {
  let firstNonEmpty = -1;
  let best = { index: -1, matches: 0 };
  for (let rowIndex = 0; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex] ?? [];
    if (hasContent(row) && firstNonEmpty === -1) firstNonEmpty = rowIndex;
    const matches = row.reduce((count, value) => (ALIAS_TO_FIELD.has(normalizeHeader(value)) ? count + 1 : count), 0);
    if (matches > best.matches) best = { index: rowIndex, matches };
  }
  if (best.matches > 0) return best.index;
  return firstNonEmpty === -1 ? 0 : firstNonEmpty;
}

function columnMapFromHeaders(headers) {
  const canonicalToIndex = new Map();
  const duplicateFields = new Set();
  for (const [index, header] of headers.entries()) {
    const canonical = ALIAS_TO_FIELD.get(normalizeHeader(header));
    if (!canonical) continue;
    if (canonicalToIndex.has(canonical)) duplicateFields.add(canonical);
    else canonicalToIndex.set(canonical, index);
  }
  if (duplicateFields.size) {
    throw new SyncError(`Workbook has duplicate headers for: ${[...duplicateFields].join(", ")}`, "DUPLICATE_HEADER");
  }
  return canonicalToIndex;
}

function rowFromSheetValues(row, headers, canonicalToIndex, rowNumber) {
  const output = { id: "", ...emptySourceFields(), ...emptyManualFields(), _extra: {} };
  for (const field of ALL_FIELDS) {
    const index = canonicalToIndex.get(field);
    if (index !== undefined) output[field] = jsonValue(row[index], field);
  }
  for (const [index, header] of headers.entries()) {
    if (!header || ALIAS_TO_FIELD.has(normalizeHeader(header))) continue;
    output._extra[String(header)] = jsonValue(row[index], "");
  }
  if (isEmptyValue(output.id)) output.id = deriveStableId(output, `workbook row ${rowNumber}`);
  output.id = String(output.id).trim();
  if (isEmptyValue(output.status)) output.status = "Not applied";
  return output;
}

async function readRangeValues(range) {
  if (!range) return [];
  const values = await range.values;
  return Array.isArray(values) ? values : [];
}

async function readWorkbookTarget(workbook, sheetName) {
  const sheet = sheetName ? workbook.worksheets.getItem(sheetName) : workbook.worksheets.getItemAt(0);
  if (!sheet) throw new SyncError("Workbook has no worksheet to update", "MISSING_SHEET");

  let usedRange;
  try {
    usedRange = sheet.getUsedRange();
  } catch {
    usedRange = null;
  }
  const values = await readRangeValues(usedRange);
  const headerRow = findHeaderRow(values);
  const headers = (values[headerRow] ?? []).map((value, index) => {
    const header = String(value ?? "").trim();
    return header || `extra_${index + 1}`;
  });
  const canonicalToIndex = columnMapFromHeaders(headers);
  const existingRows = [];
  for (let rowIndex = headerRow + 1; rowIndex < values.length; rowIndex += 1) {
    const row = values[rowIndex] ?? [];
    if (!hasContent(row)) continue;
    existingRows.push(rowFromSheetValues(row, headers, canonicalToIndex, rowIndex + 1));
  }
  assertUniqueIds(existingRows, "existing workbook");
  return { sheet, values, headerRow, headers, canonicalToIndex, existingRows };
}

function uniqueHeaderLabel(field, headers) {
  const label = OUTPUT_HEADER_LABELS[field] ?? field;
  if (!headers.some((header) => normalizeHeader(header) === normalizeHeader(label))) return label;
  let index = 2;
  while (headers.some((header) => normalizeHeader(header) === normalizeHeader(`${label}_${index}`))) index += 1;
  return `${label}_${index}`;
}

function finalHeaders(existingHeaders) {
  const headers = existingHeaders.length ? [...existingHeaders] : [];
  for (const field of ALL_FIELDS) {
    if (!headers.some((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === field)) {
      const label = uniqueHeaderLabel(field, headers);
      if (field === "domain") {
        const roleIndex = headers.findIndex((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === "role");
        if (roleIndex >= 0) headers.splice(roleIndex + 1, 0, label);
        else headers.push(label);
      } else if (field === "source") {
        const sourceUrlIndex = headers.findIndex((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === "source_url");
        if (sourceUrlIndex >= 0) headers.splice(sourceUrlIndex + 1, 0, label);
        else headers.push(label);
      } else headers.push(label);
    }
  }
  const postedIndex = headers.findIndex((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === "date_posted");
  const locationIndex = headers.findIndex((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === "location");
  if (postedIndex >= 0 && locationIndex >= 0 && postedIndex !== locationIndex + 1) {
    const [postedHeader] = headers.splice(postedIndex, 1);
    const updatedLocationIndex = headers.findIndex((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === "location");
    headers.splice(updatedLocationIndex + 1, 0, postedHeader);
  }
  return headers;
}

function columnLetter(index) {
  let number = index + 1;
  let output = "";
  while (number > 0) {
    const remainder = (number - 1) % 26;
    output = String.fromCharCode(65 + remainder) + output;
    number = Math.floor((number - 1) / 26);
  }
  return output;
}

function rowCells(row, headers) {
  return headers.map((header) => {
    const canonical = ALIAS_TO_FIELD.get(normalizeHeader(header));
    if (canonical) return workbookValue(row[canonical], canonical);
    return workbookValue(row._extra?.[header], "");
  });
}

function rangeAddress(startRowZero, rowCount, columnCount) {
  const firstRow = startRowZero + 1;
  const lastRow = startRowZero + Math.max(rowCount, 1);
  return `${columnLetter(0)}${firstRow}:${columnLetter(columnCount - 1)}${lastRow}`;
}

function tableHeaderValues(table) {
  try {
    const values = table.getHeaderRowRange()?.values;
    return Array.isArray(values) && Array.isArray(values[0]) ? values[0].map((value) => String(value ?? "")) : [];
  } catch {
    return [];
  }
}

function tableDataCount(table) {
  try {
    const values = table.getDataRows()?.values;
    return Array.isArray(values) ? values.length : 0;
  } catch {
    return 0;
  }
}

function sameHeaders(a, b) {
  return a.length === b.length && a.every((value, index) => normalizeHeader(value) === normalizeHeader(b[index]));
}

function rebuildTable(sheet, headerRow, headers, mergedRows) {
  const existingTables = [...(sheet.tables?.items ?? [])];
  // Rebuild the tracker table after writing the complete union. Direct cell
  // writes do not resize imported tables, and appending through table.rows.add
  // after those writes can duplicate rows in some artifact-tool versions.
  // The sheet is owned by this tracker, so replacing its table keeps filters
  // aligned without touching cell values or other worksheet content.
  for (const table of existingTables) table.delete();
  const rowCount = Math.max(mergedRows.length, 0);
  const address = rangeAddress(headerRow, rowCount + 1, headers.length);
  const table = sheet.tables.add(address, true, "JobsTable");
  table.style = "TableStyleMedium2";
  table.showFilterButton = true;
  table.showHeaders = true;
  return table;
}

function applyWorkbookFormatting(sheet, headerRow, headers, rows) {
  const headerRange = sheet.getRangeByIndexes(headerRow, 0, 1, headers.length);
  const bodyHeight = Math.max(rows.length, 1);
  const bodyRange = sheet.getRangeByIndexes(headerRow + 1, 0, bodyHeight, headers.length);
  const fullRange = sheet.getRangeByIndexes(headerRow, 0, bodyHeight + 1, headers.length);

  sheet.showGridLines = false;
  fullRange.format.font = { name: "Arial", size: 10, color: "#1F2937" };
  fullRange.format.verticalAlignment = "center";
  headerRange.format = {
    fill: "#1F4E78",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    horizontalAlignment: "center",
    verticalAlignment: "center",
    wrapText: true,
    borders: { preset: "outside", style: "thin", color: "#1F4E78" },
  };
  bodyRange.format.wrapText = false;
  bodyRange.format.borders = {
    insideHorizontal: { style: "thin", color: "#D9E2F3" },
    bottom: { style: "thin", color: "#D9E2F3" },
  };

  const indexOf = (field) => headers.findIndex((header) => ALIAS_TO_FIELD.get(normalizeHeader(header)) === field);
  const widthByField = {
    id: 20,
    company: 24,
    role: 30,
    domain: 24,
    agent_tier: 12,
    match_score: 12,
    best_resume: 20,
    eligibility: 18,
    ranking_confidence: 18,
    ranking_confidence_reason: 42,
    manual_priority_override: 16,
    url: 42,
    job_id: 18,
    location: 24,
    jd: 56,
    skills: 32,
    visa_sponsorship: 18,
    visa_evidence: 36,
    source_url: 42,
    source: 28,
    date_posted: 16,
    discovered_at: 16,
    last_seen: 16,
    season: 14,
    status: 18,
    applied_date: 16,
    deadline: 18,
    oa_date: 16,
    interview_date: 16,
    notes: 38,
    linkedin_contacts: 28,
    removed: 12,
    strong_matches: 42,
    missing_requirements: 42,
    tailoring_suggestions: 48,
    ranking_explanation: 54,
    resume_version: 20,
    scoring_version: 16,
    last_scored: 18,
  };
  for (const [field, width] of Object.entries(widthByField)) {
    const index = indexOf(field);
    if (index < 0) continue;
    sheet.getRangeByIndexes(headerRow, index, bodyHeight + 1, 1).format.columnWidth = width;
  }

  for (const field of ["jd", "skills", "visa_evidence", "notes", "linkedin_contacts", "strong_matches", "missing_requirements", "tailoring_suggestions", "ranking_explanation", "ranking_confidence_reason"]) {
    const index = indexOf(field);
    if (index >= 0) sheet.getRangeByIndexes(headerRow + 1, index, bodyHeight, 1).format.wrapText = true;
  }
  for (const field of DATE_FIELDS) {
    const index = indexOf(field);
    if (index >= 0) sheet.getRangeByIndexes(headerRow + 1, index, bodyHeight, 1).setNumberFormat("yyyy-mm-dd");
  }

  const statusIndex = indexOf("status");
  let validationApplied = false;
  if (statusIndex >= 0 && rows.length > 0) {
    const statusRange = sheet.getRangeByIndexes(headerRow + 1, statusIndex, rows.length, 1);
    try {
      statusRange.dataValidation = { rule: { type: "list", values: STATUS_VALUES } };
      validationApplied = true;
    } catch {
      try {
        sheet.dataValidations.add({
          range: statusRange.address,
          rule: { type: "list", values: STATUS_VALUES },
        });
        validationApplied = true;
      } catch {
        // Validation is an enhancement. A filterable table remains useful when a
        // runtime does not expose data validation on imported ranges.
      }
    }
    try {
      statusRange.conditionalFormats.add("containsText", {
        text: "Applied",
        format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
      });
      statusRange.conditionalFormats.add("containsText", {
        text: "Interviewing",
        format: { fill: "#FEF3C7", font: { color: "#92400E", bold: true } },
      });
    } catch {
      // Conditional formatting is optional across artifact-tool versions.
    }
  }
  const overrideIndex = indexOf("manual_priority_override");
  if (overrideIndex >= 0 && rows.length > 0) {
    const overrideRange = sheet.getRangeByIndexes(headerRow + 1, overrideIndex, rows.length, 1);
    try {
      overrideRange.dataValidation = { rule: { type: "list", values: TIER_VALUES } };
    } catch {
      try {
        sheet.dataValidations.add({ range: overrideRange.address, rule: { type: "list", values: TIER_VALUES } });
      } catch {
        // A plain editable column still preserves manual overrides.
      }
    }
  }
  try {
    sheet.freezePanes.freezeRows(headerRow + 1);
    sheet.freezePanes.freezeColumns(Math.min(2, headers.length));
  } catch {
    // Older artifact-tool builds may not expose both freeze operations.
  }
  return { validationApplied };
}

async function fileSnapshot(filePath) {
  try {
    const [stat, bytes] = await Promise.all([fs.stat(filePath), fs.readFile(filePath)]);
    return {
      exists: true,
      size: stat.size,
      mtimeMs: stat.mtimeMs,
      sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
    };
  } catch (error) {
    if (error?.code === "ENOENT") return { exists: false };
    throw error;
  }
}

function sameSnapshot(before, after) {
  if (before.exists !== after.exists) return false;
  if (!before.exists) return true;
  return before.size === after.size && before.mtimeMs === after.mtimeMs && before.sha256 === after.sha256;
}

export function excelLockPath(outputPath) {
  const absolute = path.resolve(outputPath);
  return path.join(path.dirname(absolute), `~$${path.basename(absolute)}`);
}

async function assertNoExcelLock(outputPath) {
  const lockPath = excelLockPath(outputPath);
  try {
    await fs.access(lockPath);
  } catch (error) {
    if (error?.code === "ENOENT") return;
    throw error;
  }
  throw new SyncError(`Excel lock file exists at ${lockPath}. Close the workbook in Excel and retry.`, "EXCEL_LOCKED");
}

function timestampForFilename() {
  return new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
}

async function uniqueBackupPath(outputPath) {
  const base = `${outputPath}.bak-${timestampForFilename()}-${process.pid}`;
  let candidate = base;
  let suffix = 1;
  while (true) {
    try {
      await fs.access(candidate);
      candidate = `${base}-${suffix}`;
      suffix += 1;
    } catch (error) {
      if (error?.code === "ENOENT") return candidate;
      throw error;
    }
  }
}

async function atomicWriteText(outputPath, text) {
  const directory = path.dirname(outputPath);
  const temporary = path.join(directory, `.${path.basename(outputPath)}.tmp-${process.pid}-${crypto.randomBytes(6).toString("hex")}`);
  try {
    await fs.writeFile(temporary, text, "utf8");
    await fs.rename(temporary, outputPath);
  } finally {
    await fs.rm(temporary, { force: true }).catch(() => {});
  }
}

async function readJobsFile(jobsPath) {
  let document;
  try {
    document = JSON.parse(await fs.readFile(jobsPath, "utf8"));
  } catch (error) {
    if (error instanceof SyntaxError) throw new SyncError(`Invalid jobs JSON: ${error.message}`, "INVALID_JOBS_JSON");
    throw error;
  }
  return normalizeJobsDocument(document);
}

async function readLinkedInContactsFile(contactsPath) {
  if (!contactsPath) return null;
  let document;
  try {
    document = JSON.parse(await fs.readFile(contactsPath, "utf8"));
  } catch (error) {
    if (error instanceof SyntaxError) throw new SyncError(`Invalid LinkedIn contacts JSON: ${error.message}`, "INVALID_CONTACTS_JSON");
    throw error;
  }
  const companies = document?.companies ?? document;
  if (!companies || Array.isArray(companies) || typeof companies !== "object") {
    throw new SyncError("LinkedIn contacts JSON must be an object or {\"companies\": {...}}", "INVALID_CONTACTS_JSON");
  }
  return companies;
}

export function applyLinkedInContacts(rows, companies) {
  if (!companies) return 0;
  const byCompany = new Map(
    Object.entries(companies).map(([company, value]) => [String(company).trim().toLowerCase(), displayValue(value).trim()]),
  );
  let updated = 0;
  for (const row of rows) {
    if (!isEmptyValue(row.linkedin_contacts)) continue;
    const contacts = byCompany.get(String(row.company ?? "").trim().toLowerCase());
    if (!contacts) continue;
    row.linkedin_contacts = contacts;
    updated += 1;
  }
  return updated;
}

export function removeLegacyJdPlaceholders(rows) {
  let cleared = 0;
  for (const row of rows) {
    if (String(row.jd ?? "").startsWith("Employer posting description is available.")) {
      row.jd = "";
      cleared += 1;
    }
  }
  return cleared;
}

function websiteDocument(rows, updatedAt = new Date()) {
  return {
    jobs: rows.map((row) => {
      const json = {};
      for (const field of ALL_FIELDS) json[field] = jsonValue(row[field], field);
      return json;
    }),
    updated_at: updatedAt.toISOString(),
  };
}

function checkOutputPaths(outputPath, jsonPath, jobsPath) {
  const output = path.resolve(outputPath);
  const json = path.resolve(jsonPath);
  const jobs = path.resolve(jobsPath);
  if (output === json) throw new SyncError("--json-output must be different from --output", "INVALID_PATHS");
  if (output === jobs) throw new SyncError("--output must be different from --jobs", "INVALID_PATHS");
}

export async function syncJobs({
  jobsPath,
  outputPath,
  jsonPath,
  sheetName = "Jobs",
  contactsPath,
  sanitizeLegacyJd = false,
  beforeReplace,
}) {
  if (!jobsPath || !outputPath) throw new SyncError("jobsPath and outputPath are required", "INVALID_ARGUMENTS");
  const absoluteJobsPath = path.resolve(jobsPath);
  const absoluteOutputPath = path.resolve(outputPath);
  const absoluteJsonPath = path.resolve(jsonPath ?? absoluteOutputPath.replace(/\.[^.]+$/, "") + ".json");
  checkOutputPaths(absoluteOutputPath, absoluteJsonPath, absoluteJobsPath);
  await fs.mkdir(path.dirname(absoluteOutputPath), { recursive: true });
  await fs.mkdir(path.dirname(absoluteJsonPath), { recursive: true });

  await assertNoExcelLock(absoluteOutputPath);
  const originalSnapshot = await fileSnapshot(absoluteOutputPath);
  const [incomingRows, linkedinCompanies] = await Promise.all([
    readJobsFile(absoluteJobsPath),
    readLinkedInContactsFile(contactsPath),
  ]);

  let workbook;
  let target;
  if (originalSnapshot.exists) {
    const input = await FileBlob.load(absoluteOutputPath);
    workbook = await SpreadsheetFile.importXlsx(input);
    target = await readWorkbookTarget(workbook, sheetName === "Jobs" ? undefined : sheetName);
  } else {
    workbook = Workbook.create();
    const sheet = workbook.worksheets.add(sheetName);
    target = {
      sheet,
      values: [],
      headerRow: 0,
      headers: [],
      canonicalToIndex: new Map(),
      existingRows: [],
    };
  }

  const mergedRows = mergeJobs(target.existingRows, incomingRows);
  const contactsUpdated = applyLinkedInContacts(mergedRows, linkedinCompanies);
  const legacyJdCleared = sanitizeLegacyJd ? removeLegacyJdPlaceholders(mergedRows) : 0;
  const headers = finalHeaders(target.headers);
  const oldDataRows = Math.max(target.values.length - target.headerRow - 1, 0);
  const validationRows = Math.max(oldDataRows, mergedRows.length, 1);
  const validationColumns = Math.max(
    target.values.reduce((max, row) => Math.max(max, row?.length ?? 0), 0),
    headers.length,
  );
  // Imported workbooks keep their previous validation ranges even when a
  // column moves. Clear the whole data area before recreating the current
  // Status and Manual priority override dropdowns below.
  target.sheet.getRangeByIndexes(
    target.headerRow + 1,
    0,
    validationRows,
    validationColumns,
  ).dataValidation = null;
  if (oldDataRows > 0) {
    const clearWidth = Math.max(target.values.reduce((max, row) => Math.max(max, row?.length ?? 0), 0), headers.length);
    target.sheet.getRangeByIndexes(target.headerRow + 1, 0, oldDataRows, clearWidth).clear({ applyTo: "contents" });
  }
  target.sheet.getRangeByIndexes(target.headerRow, 0, 1, headers.length).values = [headers];
  if (mergedRows.length) {
    target.sheet.getRangeByIndexes(target.headerRow + 1, 0, mergedRows.length, headers.length).values = mergedRows.map((row) => rowCells(row, headers));
  }
  const table = rebuildTable(target.sheet, target.headerRow, headers, mergedRows);
  const formatting = applyWorkbookFormatting(target.sheet, target.headerRow, headers, mergedRows);
  workbook.recalculate();

  const temporaryXlsx = path.join(
    path.dirname(absoluteOutputPath),
    `.${path.basename(absoluteOutputPath)}.tmp-${process.pid}-${crypto.randomBytes(6).toString("hex")}`,
  );
  let backupPath = null;
  try {
    const exported = await SpreadsheetFile.exportXlsx(workbook);
    await exported.save(temporaryXlsx);

    // A small injectable seam makes the snapshot guard testable without making
    // the normal CLI asynchronous window any larger.
    if (typeof beforeReplace === "function") await beforeReplace({ outputPath: absoluteOutputPath });

    await assertNoExcelLock(absoluteOutputPath);
    const preBackupSnapshot = await fileSnapshot(absoluteOutputPath);
    if (!sameSnapshot(originalSnapshot, preBackupSnapshot)) {
      throw new ConcurrentWorkbookEditError(
        `Workbook changed while syncing. ${absoluteOutputPath} was not replaced; reload and retry.`,
      );
    }

    if (preBackupSnapshot.exists) {
      backupPath = await uniqueBackupPath(absoluteOutputPath);
      await fs.copyFile(absoluteOutputPath, backupPath);
    }

    await assertNoExcelLock(absoluteOutputPath);
    const preReplaceSnapshot = await fileSnapshot(absoluteOutputPath);
    if (!sameSnapshot(originalSnapshot, preReplaceSnapshot)) {
      throw new ConcurrentWorkbookEditError(
        `Workbook changed while creating the backup. ${absoluteOutputPath} was not replaced; reload and retry.`,
      );
    }
    await fs.rename(temporaryXlsx, absoluteOutputPath);

    const outputJson = `${JSON.stringify(websiteDocument(mergedRows), null, 2)}\n`;
    await atomicWriteText(absoluteJsonPath, outputJson);
  } finally {
    await fs.rm(temporaryXlsx, { force: true }).catch(() => {});
    // Artifact Tool may emit a neighboring inspect sidecar while exporting.
    // It is authoring scratch data, not a deliverable.
    await fs.rm(`${temporaryXlsx}.inspect.ndjson`, { force: true }).catch(() => {});
  }

  return {
    outputPath: absoluteOutputPath,
    jsonPath: absoluteJsonPath,
    backupPath,
    sheetName: target.sheet.name,
    rows: mergedRows.length,
    incomingRows: incomingRows.length,
    existingRows: target.existingRows.length,
    contactsUpdated,
    legacyJdCleared,
    statusValidation: formatting.validationApplied,
    tableName: table.name,
  };
}

/** Update workbook-owned application tracking fields and publish matching JSON. */
export async function updateApplication({ inputPath, jsonPath, id, status, sheetName = "Jobs", appliedDate, deadline, oaDate, interviewDate, notes, manualPriorityOverride, removed }) {
  if (!inputPath || !id) throw new SyncError("inputPath and id are required", "INVALID_ARGUMENTS");
  if (status !== undefined && !STATUS_VALUES.includes(status)) throw new SyncError(`Unsupported status: ${status}`, "INVALID_STATUS");
  if (manualPriorityOverride !== undefined && !TIER_VALUES.includes(manualPriorityOverride)) {
    throw new SyncError(`Unsupported priority override: ${manualPriorityOverride}`, "INVALID_TIER");
  }
  const absoluteInputPath = path.resolve(inputPath);
  const absoluteJsonPath = path.resolve(jsonPath ?? absoluteInputPath.replace(/\.[^.]+$/, "") + ".json");
  if (absoluteInputPath === absoluteJsonPath) throw new SyncError("--json-output must be different from --input", "INVALID_PATHS");
  await assertNoExcelLock(absoluteInputPath);
  const originalSnapshot = await fileSnapshot(absoluteInputPath);
  if (!originalSnapshot.exists) throw new SyncError(`Workbook does not exist: ${absoluteInputPath}`, "MISSING_WORKBOOK");

  const input = await FileBlob.load(absoluteInputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const target = await readWorkbookTarget(workbook, sheetName === "Jobs" ? undefined : sheetName);
  const rows = mergeJobs(target.existingRows, []);
  const row = rows.find((candidate) => String(candidate.id) === String(id));
  if (!row) throw new SyncError(`Job was not found: ${id}`, "JOB_NOT_FOUND");
  if (status !== undefined) row.status = status;
  if (status !== undefined && status !== "Not applied" && isEmptyValue(row.applied_date)) {
    row.applied_date = appliedDate || new Intl.DateTimeFormat("en-CA").format(new Date());
  } else if (status === "Not applied") row.applied_date = "";
  else if (appliedDate !== undefined) row.applied_date = appliedDate;
  if (deadline !== undefined) row.deadline = deadline;
  if (oaDate !== undefined) row.oa_date = oaDate;
  if (interviewDate !== undefined) row.interview_date = interviewDate;
  if (notes !== undefined) row.notes = notes;
  if (manualPriorityOverride !== undefined) row.manual_priority_override = manualPriorityOverride;
  if (removed !== undefined) row.removed = removed === true || String(removed).toLowerCase() === "yes" ? "Yes" : "No";

  const idIndex = target.canonicalToIndex.get("id");
  if (idIndex === undefined) throw new SyncError("Workbook is missing the Stable ID column", "MISSING_MANUAL_COLUMNS");
  const sheetRowIndex = target.values.findIndex(
    (values, index) => index > target.headerRow && String(jsonValue(values?.[idIndex], "id")) === String(id),
  );
  if (sheetRowIndex < 0) throw new SyncError(`Workbook row was not found: ${id}`, "JOB_NOT_FOUND");
  const updates = {
    status: row.status,
    applied_date: row.applied_date,
    deadline: row.deadline,
    oa_date: row.oa_date,
    interview_date: row.interview_date,
    notes: row.notes,
    manual_priority_override: row.manual_priority_override,
    removed: row.removed,
  };
  for (const [field, value] of Object.entries(updates)) {
    const columnIndex = target.canonicalToIndex.get(field);
    if (columnIndex === undefined) throw new SyncError(`Workbook is missing the ${OUTPUT_HEADER_LABELS[field]} column`, "MISSING_MANUAL_COLUMNS");
    target.sheet.getRangeByIndexes(sheetRowIndex, columnIndex, 1, 1).values = [[workbookValue(value, field)]];
  }
  workbook.recalculate();

  const temporaryXlsx = path.join(
    path.dirname(absoluteInputPath),
    `.${path.basename(absoluteInputPath)}.status-${process.pid}-${crypto.randomBytes(6).toString("hex")}`,
  );
  let backupPath = null;
  try {
    const exported = await SpreadsheetFile.exportXlsx(workbook);
    await exported.save(temporaryXlsx);
    await assertNoExcelLock(absoluteInputPath);
    const beforeReplace = await fileSnapshot(absoluteInputPath);
    if (!sameSnapshot(originalSnapshot, beforeReplace)) {
      throw new ConcurrentWorkbookEditError(`Workbook changed while updating status. ${absoluteInputPath} was not replaced; retry.`);
    }
    backupPath = await uniqueBackupPath(absoluteInputPath);
    await fs.copyFile(absoluteInputPath, backupPath);
    await assertNoExcelLock(absoluteInputPath);
    const finalSnapshot = await fileSnapshot(absoluteInputPath);
    if (!sameSnapshot(originalSnapshot, finalSnapshot)) {
      throw new ConcurrentWorkbookEditError(`Workbook changed while creating the status backup. ${absoluteInputPath} was not replaced; retry.`);
    }
    await fs.rename(temporaryXlsx, absoluteInputPath);
    await fs.mkdir(path.dirname(absoluteJsonPath), { recursive: true });
    await atomicWriteText(absoluteJsonPath, `${JSON.stringify(websiteDocument(rows), null, 2)}\n`);
  } finally {
    await fs.rm(temporaryXlsx, { force: true }).catch(() => {});
    await fs.rm(`${temporaryXlsx}.inspect.ndjson`, { force: true }).catch(() => {});
  }
  return { inputPath: absoluteInputPath, jsonPath: absoluteJsonPath, backupPath, id: String(id), ...updates };
}

/** Backward-compatible status-only entry point. */
export async function updateJobStatus(options) {
  return updateApplication(options);
}

/**
 * Export current workbook rows without authoring or replacing the workbook.
 * Use this for frequent manual-edit syncs; the merge writer can run only when
 * the collector has new jobs.
 */
export async function exportWorkbookJson({ inputPath, jsonPath, sheetName = "Jobs", beforePublish }) {
  if (!inputPath) throw new SyncError("inputPath is required for read-only export", "INVALID_ARGUMENTS");
  const absoluteInputPath = path.resolve(inputPath);
  const absoluteJsonPath = path.resolve(jsonPath ?? absoluteInputPath.replace(/\.[^.]+$/, "") + ".json");
  if (absoluteInputPath === absoluteJsonPath) throw new SyncError("--json-output must be different from --input", "INVALID_PATHS");
  await assertNoExcelLock(absoluteInputPath);
  const snapshot = await fileSnapshot(absoluteInputPath);
  if (!snapshot.exists) throw new SyncError(`Workbook does not exist: ${absoluteInputPath}`, "MISSING_WORKBOOK");
  const input = await FileBlob.load(absoluteInputPath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const target = await readWorkbookTarget(workbook, sheetName === "Jobs" ? undefined : sheetName);
  const rows = mergeJobs(target.existingRows, []);
  // Keep the read-only export fail-closed as well. A workbook edit during
  // import must not be published as if it were a current JSON snapshot.
  if (typeof beforePublish === "function") await beforePublish({ inputPath: absoluteInputPath });
  await assertNoExcelLock(absoluteInputPath);
  const finalSnapshot = await fileSnapshot(absoluteInputPath);
  if (!sameSnapshot(snapshot, finalSnapshot)) {
    throw new ConcurrentWorkbookEditError(
      `Workbook changed while exporting JSON. ${absoluteInputPath} was not published; retry.`,
    );
  }
  await fs.mkdir(path.dirname(absoluteJsonPath), { recursive: true });
  const outputJson = `${JSON.stringify(websiteDocument(rows), null, 2)}\n`;
  await atomicWriteText(absoluteJsonPath, outputJson);
  return {
    inputPath: absoluteInputPath,
    jsonPath: absoluteJsonPath,
    sheetName: target.sheet.name,
    rows: rows.length,
    readOnly: true,
  };
}

export function parseArgs(argv) {
  const options = { jsonPath: undefined, sheetName: "Jobs", exportJson: false, updateStatus: false, updateApplication: false, sanitizeLegacyJd: false };
  const positional = [];
  const valueFlags = new Map([
    ["--jobs", "jobsPath"],
    ["-j", "jobsPath"],
    ["--output", "outputPath"],
    ["-o", "outputPath"],
    ["--json-output", "jsonPath"],
    ["-m", "jsonPath"],
    ["--sheet", "sheetName"],
    ["--input", "inputPath"],
    ["-i", "inputPath"],
    ["--linkedin-contacts", "contactsPath"],
    ["--id", "id"],
    ["--status", "status"],
    ["--applied-date", "appliedDate"],
    ["--deadline", "deadline"],
    ["--oa-date", "oaDate"],
    ["--interview-date", "interviewDate"],
    ["--notes", "notes"],
    ["--priority-override", "manualPriorityOverride"],
    ["--removed", "removed"],
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--help" || argument === "-h") return { help: true };
    if (argument === "--export-json") {
      options.exportJson = true;
      continue;
    }
    if (argument === "--update-status") {
      options.updateStatus = true;
      continue;
    }
    if (argument === "--update-application") {
      options.updateApplication = true;
      continue;
    }
    if (argument === "--sanitize-legacy-jd") {
      options.sanitizeLegacyJd = true;
      continue;
    }
    const key = valueFlags.get(argument);
    if (key) {
      const value = argv[index + 1];
      if (value === undefined || value.startsWith("-")) throw new SyncError(`${argument} requires a value`, "INVALID_ARGUMENTS");
      options[key] = value;
      index += 1;
    } else if (argument.startsWith("-")) {
      throw new SyncError(`Unknown option: ${argument}`, "INVALID_ARGUMENTS");
    } else positional.push(argument);
  }
  if (options.updateStatus || options.updateApplication) {
    if (!options.inputPath || !options.id || (options.updateStatus && !options.status) || positional.length) {
      throw new SyncError("Usage: node src/sync.mjs --update-application --input tracker.xlsx --id stable-id [tracking fields] --json-output jobs.json", "INVALID_ARGUMENTS");
    }
    if (!options.jsonPath) options.jsonPath = path.resolve(options.inputPath).replace(/\.[^.]+$/, "") + ".json";
    return options;
  }
  if (options.exportJson) {
    if (!options.inputPath && positional[0]) options.inputPath = positional[0];
    if (positional.length > 1) throw new SyncError("Read-only export accepts one workbook path", "INVALID_ARGUMENTS");
    if (!options.inputPath) {
      throw new SyncError("Usage: node src/sync.mjs --export-json --input tracker.xlsx --json-output jobs.json", "INVALID_ARGUMENTS");
    }
    if (!options.jsonPath) options.jsonPath = path.resolve(options.inputPath).replace(/\.[^.]+$/, "") + ".json";
    return options;
  }
  if (!options.jobsPath && positional[0]) options.jobsPath = positional[0];
  if (!options.outputPath && positional[1]) options.outputPath = positional[1];
  if (positional.length > 2) throw new SyncError("Expected jobs JSON and output XLSX paths", "INVALID_ARGUMENTS");
  if (!options.jobsPath || !options.outputPath) {
    throw new SyncError("Usage: node src/sync.mjs --jobs jobs.json --output tracker.xlsx [--json-output merged.json]", "INVALID_ARGUMENTS");
  }
  if (!options.jsonPath) options.jsonPath = path.resolve(options.outputPath).replace(/\.[^.]+$/, "") + ".json";
  return options;
}

function usage() {
  return [
    "Usage:",
    "  node src/sync.mjs --jobs jobs.json --output tracker.xlsx [--json-output merged.json] [--sheet Jobs]",
    "  node src/sync.mjs jobs.json tracker.xlsx",
    "  node src/sync.mjs --export-json --input tracker.xlsx --json-output merged.json",
    "  node src/sync.mjs --update-status --input tracker.xlsx --id stable-id --status Applied --json-output merged.json",
    "  node src/sync.mjs --update-application --input tracker.xlsx --id stable-id [--status Applied] [--priority-override 'Tier 1'] [--deadline YYYY-MM-DD] [--oa-date YYYY-MM-DD] [--interview-date YYYY-MM-DD] [--notes text] [--removed Yes] --json-output merged.json",
    "",
    "The jobs document is a JSON array or {\"jobs\": [...]}.",
    "Every record needs id/stable_id, job_id, or url. id is the canonical stable key.",
    "Existing workbook values for status, application dates, notes, contacts, and priority overrides are retained by id.",
    "--linkedin-contacts fills blank LinkedIn contact cells from a company-to-contacts JSON map.",
    "--sanitize-legacy-jd removes obsolete generic JD placeholders from older tracker builds.",
    "--export-json imports and exports the current workbook read-only for frequent manual-edit syncs.",
  ].join("\n");
}

if (import.meta.url === `file://${process.argv[1]}`) {
  try {
    const options = parseArgs(process.argv.slice(2));
    if (options.help) {
      console.log(usage());
      process.exit(0);
    }
    const result = options.updateStatus || options.updateApplication
      ? await updateApplication(options)
      : options.exportJson
        ? await exportWorkbookJson(options)
        : await syncJobs(options);
    console.log(JSON.stringify(result, null, 2));
  } catch (error) {
    console.error(`Excel sync failed: ${error.message}`);
    process.exitCode = 1;
  }
}
