import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";
import {
  applyLinkedInContacts,
  ConcurrentWorkbookEditError,
  excelLockPath,
  exportWorkbookJson,
  humanizeSource,
  mergeJobs,
  normalizeJobsDocument,
  removeLegacyJdPlaceholders,
  syncJobs,
  updateApplication,
  updateJobStatus,
} from "../src/sync.mjs";

async function tempDir() {
  return fs.mkdtemp(path.join(os.tmpdir(), "internship-excel-test-"));
}

async function writeFixtureWorkbook(filePath) {
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("Jobs");
  sheet.getRange("A1:T3").values = [
    [
      "id",
      "company",
      "role",
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
      "status",
      "applied_date",
      "notes",
      "linkedin_contacts",
    ],
    [
      "job-1",
      "Acme",
      "Data Intern",
      "https://example.test/job-1",
      "job-1",
      "New York",
      "Build reports",
      "SQL",
      true,
      "Company careers page",
      "https://example.test/careers",
      "Greenhouse: Acme",
      new Date("2026-08-15T00:00:00.000Z"),
      new Date("2026-09-01T00:00:00.000Z"),
      new Date("2026-09-02T00:00:00.000Z"),
      "Summer 2027",
      "Applied",
      new Date("2026-09-03T00:00:00.000Z"),
      "Sent resume",
      "Jane Doe",
    ],
    [
      "job-old",
      "Old Co",
      "Research Intern",
      "https://example.test/old",
      "job-old",
      "Remote",
      "Read papers",
      "Python",
      "Unknown",
      "",
      "",
      "Legacy import",
      "",
      new Date("2026-08-01T00:00:00.000Z"),
      new Date("2026-08-02T00:00:00.000Z"),
      "Summer 2027",
      "Interested",
      "",
      "Keep this row",
      "",
    ],
  ];
  const table = sheet.tables.add("A1:T3", true, "JobsTable");
  table.style = "TableStyleMedium2";
  const output = await SpreadsheetFile.exportXlsx(workbook);
  await output.save(filePath);
}

async function readRows(filePath) {
  const input = await FileBlob.load(filePath);
  const workbook = await SpreadsheetFile.importXlsx(input);
  const sheet = workbook.worksheets.getItemAt(0);
  return sheet.getRange("A1:T10").values;
}

test("mergeJobs preserves Excel manual fields and appends only incoming jobs", () => {
  const existing = [
    {
      id: "job-1",
      company: "Acme",
      status: "Applied",
      applied_date: "2026-09-03",
      notes: "Sent resume",
      linkedin_contacts: "Jane Doe",
      _extra: {},
    },
  ];
  const incoming = normalizeJobsDocument([
    {
      id: "job-1",
      company: "Acme Updated",
      role: "Data Intern",
      status: "Not applied",
    },
    { job_id: "job-2", company: "New Co", role: "SWE Intern", url: "https://example.test/job-2" },
  ]);
  const merged = mergeJobs(existing, incoming);
  assert.equal(merged.length, 2);
  assert.equal(merged[0].company, "Acme Updated");
  assert.equal(merged[0].status, "Applied");
  assert.equal(merged[0].notes, "Sent resume");
  assert.equal(merged[1].id, "company:new co|job:job-2");
  assert.equal(merged[1].status, "Not applied");
  assert.equal(merged[1].applied_date, "");
});

test("stable ids namespace duplicate requisition ids by company and normalize Excel dates", () => {
  const jobs = normalizeJobsDocument({ records: [
    { company: "Acme", job_id: "123", discovered_at: 46374 },
    { company: "Beta", job_id: "123", discovered_at: 46374 },
  ] });
  assert.notEqual(jobs[0].id, jobs[1].id);
  assert.match(jobs[0].id, /^company:acme\|job:123$/);
  assert.equal(jobs[0].discovered_at, "2026-12-18");
  const timestamp = normalizeJobsDocument([{ company: "Acme", job_id: "124", discovered_at: 46274.34502314815 }]);
  assert.equal(timestamp[0].discovered_at, "2026-09-09T08:16:50.000Z");
  const merged = mergeJobs(
    [{ id: jobs[0].id, discovered_at: "2026-01-01", last_seen: "2026-01-02", _extra: {} }],
    [{ ...jobs[0], discovered_at: "2026-02-01", last_seen: "2026-02-02" }],
  );
  assert.equal(merged[0].discovered_at, "2026-01-01");
  assert.equal(merged[0].last_seen, "2026-02-02");
});

test("date posted is normalized as a source date and preserved when incoming data omits it", () => {
  const jobs = normalizeJobsDocument([
    { id: "job-1", company: "Acme", date_posted: 46250 },
    { id: "job-2", company: "Beta", datePosted: "2026-08-24T14:44:49.699+00:00" },
  ]);
  assert.equal(jobs[0].date_posted, "2026-08-16");
  assert.equal(jobs[1].date_posted, "2026-08-24T14:44:49.699+00:00");

  const merged = mergeJobs(
    [{ id: "job-1", date_posted: "2026-08-15", _extra: {} }],
    [{ id: "job-1", company: "Acme", date_posted: "", _extra: {} }],
  );
  assert.equal(merged[0].date_posted, "2026-08-15");
});

test("source is humanized, stays distinct from Source URL, and preserves first discovery", () => {
  const incoming = normalizeJobsDocument([
    {
      id: "job-1",
      source: "greenhouse:scaleai,simplify",
      source_url: "https://jobright.ai/jobs/summer-2027",
    },
  ]);
  assert.equal(humanizeSource("greenhouse:scaleai,simplify"), "Greenhouse, Simplify");
  assert.equal(incoming[0].source, "Simplify");
  assert.equal(incoming[0].source_url, "https://jobright.ai/jobs/summer-2027");

  const merged = mergeJobs(
    [{ id: "job-1", source: "Jobright", source_url: "https://jobright.ai/jobs/summer-2027", _extra: {} }],
    [{ id: "job-1", source: "", source_url: "", _extra: {} }],
  );
  assert.equal(merged[0].source, "Jobright");
  assert.equal(merged[0].source_url, "https://jobright.ai/jobs/summer-2027");

  const multiSource = mergeJobs(
    [{ id: "job-1", source: "Instagram", source_url: "", _extra: {} }],
    [{ id: "job-1", source: "simplify", source_url: "", _extra: {} }],
  );
  assert.equal(multiSource[0].source, "Instagram");
});

test("domain is a source field and status updates write through to workbook JSON", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    const jsonPath = path.join(directory, "merged.json");
    await fs.writeFile(jobsPath, JSON.stringify([{ id: "job-1", company: "Acme", role: "ML Intern", domain: "Machine Learning / AI" }]));
    await syncJobs({ jobsPath, outputPath, jsonPath });
    const result = await updateJobStatus({ inputPath: outputPath, jsonPath, id: "job-1", status: "Applied", appliedDate: "2026-09-09" });
    assert.equal(result.status, "Applied");
    const document = JSON.parse(await fs.readFile(jsonPath, "utf8"));
    assert.equal(document.jobs[0].domain, "Machine Learning / AI");
    assert.equal(document.jobs[0].status, "Applied");
    assert.equal(document.jobs[0].applied_date, "2026-09-09");
    await updateJobStatus({ inputPath: outputPath, jsonPath, id: "job-1", status: "Not applied" });
    const reset = JSON.parse(await fs.readFile(jsonPath, "utf8"));
    assert.equal(reset.jobs[0].applied_date, "");
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("application tracking writes priority, OA, interview, deadline, notes, and removal fields", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    const jsonPath = path.join(directory, "merged.json");
    await fs.writeFile(jobsPath, JSON.stringify([{ id: "job-1", company: "Acme", role: "SWE Intern" }]));
    await syncJobs({ jobsPath, outputPath, jsonPath });
    await updateApplication({ inputPath: outputPath, jsonPath, id: "job-1", status: "OA", appliedDate: "2026-09-10", deadline: "2026-09-20", oaDate: "2026-09-15", interviewDate: "2026-09-18", notes: "Assessment received", manualPriorityOverride: "Tier 1", removed: "Yes" });
    const job = JSON.parse(await fs.readFile(jsonPath, "utf8")).jobs[0];
    assert.equal(job.status, "OA");
    assert.equal(job.applied_date, "2026-09-10");
    assert.equal(job.deadline, "2026-09-20");
    assert.equal(job.oa_date, "2026-09-15");
    assert.equal(job.interview_date, "2026-09-18");
    assert.equal(job.notes, "Assessment received");
    assert.equal(job.manual_priority_override, "Tier 1");
    assert.equal(job.removed, "Yes");
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("Interested does not create an application date and clears a previous one", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    const jsonPath = path.join(directory, "merged.json");
    await fs.writeFile(jobsPath, JSON.stringify([{ id: "job-1", company: "Example Co", role: "Intern", url: "https://example.test/job-1" }]));
    await syncJobs({ jobsPath, outputPath, jsonPath });
    await updateApplication({ inputPath: outputPath, jsonPath, id: "job-1", status: "Interested" });
    let feed = JSON.parse(await fs.readFile(jsonPath, "utf8"));
    assert.equal(feed.jobs[0].applied_date, "");
    await updateApplication({ inputPath: outputPath, jsonPath, id: "job-1", status: "Applied", appliedDate: "2026-09-02" });
    feed = JSON.parse(await fs.readFile(jsonPath, "utf8"));
    assert.equal(feed.jobs[0].applied_date, "2026-09-02");
    await updateApplication({ inputPath: outputPath, jsonPath, id: "job-1", status: "Interested" });
    feed = JSON.parse(await fs.readFile(jsonPath, "utf8"));
    assert.equal(feed.jobs[0].applied_date, "");
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("syncJobs creates a formatted, filterable workbook and JSON sidecar", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    await fs.writeFile(
      jobsPath,
      JSON.stringify({
        jobs: [
          {
            id: "new-1",
            company: "New Co",
            role: "Product Intern",
            url: "https://example.test/new-1",
            location: "Boston",
            skills: ["SQL", "Python"],
            discovered_at: "2026-09-09",
          },
        ],
      }),
    );
    const result = await syncJobs({ jobsPath, outputPath });
    assert.equal(result.rows, 1);
    assert.equal(result.backupPath, null);
    const document = JSON.parse(await fs.readFile(result.jsonPath, "utf8"));
    assert.ok(document.updated_at);
    const merged = document.jobs;
    assert.equal(merged[0].id, "new-1");
    assert.equal(merged[0].status, "Not applied");
    assert.equal(merged[0].skills, "SQL, Python");
    const input = await FileBlob.load(outputPath);
    const workbook = await SpreadsheetFile.importXlsx(input);
    const sheet = workbook.worksheets.getItemAt(0);
    const inspected = await workbook.inspect({ kind: "table", sheetId: sheet.name, range: "A1:U4", maxChars: 5000 });
    assert.match(inspected.ndjson, /Company/);
    assert.equal(sheet.tables.items.length, 1);
    assert.equal(sheet.tables.items[0].showFilterButton, true);
    assert.deepEqual(sheet.getRange("A1:U2").values[0].slice(0, 2), ["Company", "Role"]);
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("human-facing headers survive a second merge and read-only export", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    const exportPath = path.join(directory, "export.json");
    const job = {
      id: "roundtrip-1",
      company: "Roundtrip Co",
      role: "Data Intern",
      url: "https://example.test/roundtrip-1",
      job_id: "roundtrip-1",
      skills: ["Python", "SQL"],
      discovered_at: "2026-09-01",
      last_seen: "2026-09-09",
    };
    await fs.writeFile(jobsPath, JSON.stringify([job]));
    await syncJobs({ jobsPath, outputPath });
    const firstExport = await exportWorkbookJson({ inputPath: outputPath, jsonPath: exportPath });
    const firstDocument = JSON.parse(await fs.readFile(firstExport.jsonPath, "utf8"));
    assert.equal(firstDocument.jobs[0].url, job.url);
    assert.equal(firstDocument.jobs[0].skills, "Python, SQL");

    await fs.writeFile(jobsPath, JSON.stringify([{ ...job, role: "Data Engineering Intern" }]));
    await syncJobs({ jobsPath, outputPath });
    const input = await FileBlob.load(outputPath);
    const workbook = await SpreadsheetFile.importXlsx(input);
    const headers = workbook.worksheets.getItemAt(0).getUsedRange().values[0];
    assert.equal(headers.length, 39);
    assert.equal(headers.filter((header) => header === "Domain").length, 1);
    assert.equal(headers.filter((header) => header === "Source").length, 1);
    assert.equal(headers.filter((header) => header === "Date posted").length, 1);
    assert.equal(headers.indexOf("Source"), headers.indexOf("Source URL") + 1);
    assert.equal(headers.indexOf("Date posted"), headers.indexOf("Location") + 1);
    assert.equal(headers.filter((header) => header === "Role link").length, 1);
    assert.equal(headers.filter((header) => header === "Skills needed").length, 1);
    assert.equal(headers.some((header) => String(header).endsWith("_2")), false);

    const secondExport = await exportWorkbookJson({ inputPath: outputPath, jsonPath: exportPath });
    const secondDocument = JSON.parse(await fs.readFile(secondExport.jsonPath, "utf8"));
    assert.equal(secondDocument.jobs[0].url, job.url);
    assert.equal(secondDocument.jobs[0].skills, "Python, SQL");
    assert.equal(secondDocument.jobs[0].role, "Data Engineering Intern");
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("syncJobs keeps existing rows and backs up before replacement", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    await writeFixtureWorkbook(outputPath);
    await fs.writeFile(jobsPath, JSON.stringify([{ id: "job-1", role: "Data Intern II" }, { id: "job-3", company: "Third Co", url: "https://example.test/job-3" }]));
    const originalHash = crypto.createHash("sha256").update(await fs.readFile(outputPath)).digest("hex");
    const result = await syncJobs({ jobsPath, outputPath });
    assert.ok(result.backupPath);
    const backupHash = crypto.createHash("sha256").update(await fs.readFile(result.backupPath)).digest("hex");
    assert.equal(backupHash, originalHash);
    const document = JSON.parse(await fs.readFile(result.jsonPath, "utf8"));
    const merged = document.jobs;
    assert.equal(merged.length, 3);
    assert.equal(merged.find((row) => row.id === "job-1").status, "Applied");
    assert.equal(merged.find((row) => row.id === "job-1").source, "Greenhouse");
    assert.equal(merged.find((row) => row.id === "job-1").date_posted, "2026-08-15");
    assert.equal(merged.find((row) => row.id === "job-old").notes, "Keep this row");
    assert.equal(merged.find((row) => row.id === "job-3").status, "Not applied");
    const exportPath = path.join(directory, "manual-edit-export.json");
    const exportResult = await exportWorkbookJson({ inputPath: outputPath, jsonPath: exportPath });
    assert.equal(exportResult.readOnly, true);
    const exported = JSON.parse(await fs.readFile(exportPath, "utf8"));
    assert.equal(exported.jobs.find((row) => row.id === "job-1").status, "Applied");
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("syncJobs refuses Excel lock files", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    await fs.writeFile(jobsPath, JSON.stringify([{ id: "job-1", company: "Acme", url: "https://example.test/job-1" }]));
    const lockPath = excelLockPath(outputPath);
    await fs.writeFile(lockPath, "lock");
    await assert.rejects(syncJobs({ jobsPath, outputPath }), (error) => error.code === "EXCEL_LOCKED");
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("syncJobs refuses a workbook that changes during preparation", async () => {
  const directory = await tempDir();
  try {
    const jobsPath = path.join(directory, "jobs.json");
    const outputPath = path.join(directory, "internships.xlsx");
    await writeFixtureWorkbook(outputPath);
    await fs.writeFile(jobsPath, JSON.stringify([{ id: "job-1", role: "Data Intern II" }]));
    const original = await fs.readFile(outputPath);
    await assert.rejects(
      syncJobs({
        jobsPath,
        outputPath,
        beforeReplace: async () => fs.appendFile(outputPath, "concurrent edit"),
      }),
      (error) => error instanceof ConcurrentWorkbookEditError,
    );
    assert.deepEqual(await fs.readFile(outputPath), Buffer.concat([original, Buffer.from("concurrent edit")]));
    const backups = (await fs.readdir(directory)).filter((file) => file.includes(".bak-"));
    assert.equal(backups.length, 0);
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("read-only export refuses a workbook that changes before JSON publish", async () => {
  const directory = await tempDir();
  try {
    const outputPath = path.join(directory, "internships.xlsx");
    const jsonPath = path.join(directory, "merged.json");
    await writeFixtureWorkbook(outputPath);
    await assert.rejects(
      exportWorkbookJson({
        inputPath: outputPath,
        jsonPath,
        beforePublish: async () => fs.appendFile(outputPath, "concurrent edit"),
      }),
      (error) => error instanceof ConcurrentWorkbookEditError,
    );
    await assert.rejects(fs.access(jsonPath));
  } finally {
    await fs.rm(directory, { recursive: true, force: true });
  }
});

test("LinkedIn enrichment fills blank contacts without replacing user-entered contacts", () => {
  const rows = [
    { company: "TikTok", linkedin_contacts: "" },
    { company: "TikTok", linkedin_contacts: "Existing contact" },
    { company: "AMD", linkedin_contacts: "" },
  ];
  assert.equal(applyLinkedInContacts(rows, { tiktok: "Jiachen Tan (2nd)" }), 1);
  assert.deepEqual(rows.map((row) => row.linkedin_contacts), ["Jiachen Tan (2nd)", "Existing contact", ""]);
});

test("legacy generic JD placeholders are removed while useful excerpts remain", () => {
  const rows = [
    { jd: "Employer posting description is available. JD excerpt: script noise" },
    { jd: "JD excerpt: Build production software with the team." },
  ];
  assert.equal(removeLegacyJdPlaceholders(rows), 1);
  assert.deepEqual(rows.map((row) => row.jd), ["", "JD excerpt: Build production software with the team."]);
});
