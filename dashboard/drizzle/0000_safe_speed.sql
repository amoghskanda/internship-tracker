CREATE TABLE `applications` (
	`id` text PRIMARY KEY NOT NULL,
	`status` text DEFAULT 'Not applied' NOT NULL,
	`applied_date` text DEFAULT '' NOT NULL,
	`deadline` text DEFAULT '' NOT NULL,
	`oa_date` text DEFAULT '' NOT NULL,
	`interview_date` text DEFAULT '' NOT NULL,
	`notes` text DEFAULT '' NOT NULL,
	`removed` integer DEFAULT false NOT NULL,
	`updated_at` text NOT NULL
);
