CREATE TABLE `call_leases` (
	`user_id` text PRIMARY KEY NOT NULL,
	`nonce` text NOT NULL,
	`expires_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `call_limits` (
	`user_id` text PRIMARY KEY NOT NULL,
	`window` integer NOT NULL,
	`count` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `connections` (
	`user_id` text PRIMARY KEY NOT NULL,
	`endpoint` text NOT NULL,
	`credential` text NOT NULL,
	`updated_at` text NOT NULL
);
