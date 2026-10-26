import {defineConfig} from 'drizzle-kit';
export default defineConfig({dialect:'sqlite',schema:'./gateway/db/schema.ts',out:'./gateway/drizzle'});
