import {sqliteTable,text,integer} from 'drizzle-orm/sqlite-core';
export const connections=sqliteTable('connections',{userId:text('user_id').primaryKey(),endpoint:text('endpoint').notNull(),credential:text('credential').notNull(),updatedAt:text('updated_at').notNull()});
export const callLeases=sqliteTable('call_leases',{userId:text('user_id').primaryKey(),nonce:text('nonce').notNull(),expiresAt:integer('expires_at').notNull()});
export const callLimits=sqliteTable('call_limits',{userId:text('user_id').primaryKey(),window:integer('window').notNull(),count:integer('count').notNull()});
