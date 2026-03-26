# Memla Head-to-Head Coding Demo

- Teacher model: `qwen3.5:9b`
- Repo: `..\external\trpc-examples-next-prisma-starter`
- Cases: `12`

## Aggregate Result

- Raw teacher file recall: `0.5417`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.6667`
- Memla plan command recall: `0.9167`
- Memla combined file recall: `0.7917`
- Memla combined command recall: `0.9167`

## Case 1

**Prompt**: Add created and updated timestamps to the Post table in the Next.js Prisma example.

- Expected files: `src/pages/post/[id].tsx, src/server/routers/post.ts`
- Expected commands: `npm run build, npm run lint`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `Next.js`
- Commands: `*Note: If you are using a production database, ensure you run `npx prisma migrate deploy` instead of `dev`.*`
- Answer excerpt: To add `createdAt` and `updatedAt` timestamps to the `Post` table in your Next.js Prisma project, you need to modify the Prisma schema file. ### 1. Modify the Schema Open your `prisma/schema.prisma` file and update the `Post` model. **Fi...

**Memla in front**

- Prior trace ids: `5, 6, 8`
- Plan files: `src/server/routers/post.ts, src/server/routers/post.test.ts, prisma/migrations/20220307124425_non_unique_timestamps/migration.sql, prisma/schema.prisma, src/pages/post/[id].tsx, .github/workflows/main.yml`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `app_shell, routing_surface, service_boundary, state_holder`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `src/server/routers/post.ts, src/server/routers/post.test.ts, prisma/migrations/20220307124425_non_unique_timestamps/migration.sql, prisma/schema.prisma, src/pages/post/[id].tsx, .github/workflows/main.yml, Next.js`
- Combined commands: `npm run build, npm run lint, npx prisma migrate dev`
- Answer excerpt: [Thought] The user wants to add `created` and `updated` timestamps to the `Post` table in the Next.js Prisma example. Based on the retrieved memory, this is a known decision and likely involves modifying the `prisma/schema.prisma` file....
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To refactor the codebase to separate router creation logic from context handling into distinct modules, I will modify the `src/server/context
  - ts`, `src/server/routers/post
  - ts`, and `src/server/routers/_app
  - Here's the plan:

## Case 2

**Prompt**: Fix the incorrect port number in the Prisma connection string for the database.

- Expected files: `jest-playwright.config.js, jest.config.js, jest.config.ts, jest.playwright.config.ts, package.json, playwright/smoke.test.ts, prisma/seed.ts, src/server/lib/sum.test.ts, src/server/lib/sum.ts, test/playwright.test.ts`
- Expected commands: `npm run build, npm run lint`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.0`
- Memla plan command recall: `0.0`
- Memla combined file recall: `0.0`
- Memla combined command recall: `0.0`

**Raw teacher**

- Files: ``
- Commands: ``
- Answer excerpt: I need to see your current code to identify the incorrect port number in the Prisma connection string. Could you please share: 1. The file containing the Prisma connection string (likely `prisma/schema.prisma` or an environment file like...

**Memla in front**

- Prior trace ids: ``
- Plan files: ``
- Plan commands: ``
- Plan tests: ``
- Role targets: ``
- Constraint tags: ``
- Combined files: ``
- Combined commands: ``
- Answer excerpt: [Thought] The user wants to fix the incorrect port number in the Prisma connection string. Based on the retrieved memory, this is a known issue. I need to: 1. Locate the environment file (e.g., `.env.local`) or the code where the Prisma...

## Case 3

**Prompt**: Update the Next.js app to use the Vercel URL environment variable for deployment.

- Expected files: `package.json, src/pages/_app.tsx`
- Expected commands: `npm run build, npm run lint`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.5`
- Memla plan command recall: `1.0`
- Memla combined file recall: `0.5`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `Next.js, app/api/status/route.ts, components/Link.tsx`
- Commands: ``
- Answer excerpt: To update the Next.js app to use the Vercel URL environment variable, you need to modify your environment configuration files. ### Files to Update 1. **`.env.local`** (or your local `.env` file) 2. **`.env.example`** (if you maintain one...

**Memla in front**

- Prior trace ids: `6, 5, 8`
- Plan files: `next.config.ts, next-env.d.ts, src/server/routers/_app.ts, src/pages/_app.tsx, src/server/routers/app.ts, .github/workflows/main.yml`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `app_shell, routing_surface, service_boundary, state_holder`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `next.config.ts, next-env.d.ts, src/server/routers/_app.ts, src/pages/_app.tsx, src/server/routers/app.ts, .github/workflows/main.yml, Next.js, src/pages/_document.tsx`
- Combined commands: `npm run build, npm run lint`
- Answer excerpt: [Thought] The user wants to update the Next.js app to use the `VERCEL_URL` environment variable for deployment. Based on the retrieved memory, this is a known decision. I need to: 1. Locate the file where the domain or URL is configured...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To refactor the Next
  - js starter to handle loading states and improve error handling for the post router, I will modify the `src/server/routers/post
  - ts`, `src/pages/post/[id]
  - tsx`, and `src/server/routers/_app

## Case 4

**Prompt**: Uncomment the prefetch logic for posts in the index page.

- Expected files: `src/pages/index.tsx`
- Expected commands: `npm run build, npm run lint`
- Raw teacher file recall: `1.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `app/routes/index.tsx, app/routes/index.ts, Next.js, pages/index.tsx, src/pages/index.tsx`
- Commands: ``
- Answer excerpt: To uncomment the prefetch logic for posts in the index page, I need to locate the file handling the index route (likely `app/routes/index.tsx`, `app/routes/index.ts`, or a similar entry point) and find the commented-out prefetch call. Si...

**Memla in front**

- Prior trace ids: `8, 5, 6`
- Plan files: `src/server/routers/post.ts, src/pages/index.tsx, src/server/routers/post.test.ts, src/pages/post/[id].tsx, .github/workflows/main.yml, src/server/routers/_app.ts`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `app_shell, routing_surface, service_boundary, state_holder`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `src/server/routers/post.ts, src/pages/index.tsx, src/server/routers/post.test.ts, src/pages/post/[id].tsx, .github/workflows/main.yml, src/server/routers/_app.ts`
- Combined commands: `npm run build, npm run lint`
- Answer excerpt: [Thought] The user wants to uncomment the prefetch logic for posts on the index page. Based on the retrieved memory, this is a known decision involving `src/pages/index.tsx` and potentially `src/server/routers/post.ts`. I need to: 1. Ins...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update the post detail page to use the new router API instead of the old one, I will modify the `src/pages/post/[id]
  - Here's the plan:
  - **Identify current usage**: Check the current usage of the old router API in `src/pages/post/[id]
  - **Update imports**: Update the imports to use the new router API

## Case 5

**Prompt**: Fix the seed data to use the variable firstPostId instead of the hardcoded ID.

- Expected files: `prisma/seed.ts`
- Expected commands: `npm run build, npm run lint`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `seed.js, seed.ts, seedData.js, database/seeds/seed.js, migrations/seed.ts`
- Commands: ``
- Answer excerpt: To fix the seed data, I need to locate the file where the hardcoded ID is currently used and replace it with the `firstPostId` variable. Since I don't have direct access to your file system to browse the repository, I will outline the ty...

**Memla in front**

- Prior trace ids: `8`
- Plan files: `src/pages/post/[id].tsx`
- Plan commands: `npm run lint, npm run build`
- Plan tests: `npm run lint, npm run build`
- Role targets: ``
- Constraint tags: `verification_gate`
- Combined files: `src/pages/post/[id].tsx, prisma/seed.ts`
- Combined commands: `npm run lint, npm run build`
- Answer excerpt: [Thought] The user wants to fix the seed data to use a variable `firstPostId` instead of a hardcoded ID. Based on the retrieved memory, this is a known decision. I need to: 1. Locate the seed file (likely `prisma/seed.ts` or similar). 2....
- Transmutations:
  - Trade one implementation constraint for a more stable verified constraint.
- Patch steps:
  - To update the post detail page to use the new router API instead of the old one, I will modify the `src/pages/post/[id]
  - Here's the plan:
  - **Identify current usage**: Check the current usage of the old router API in `src/pages/post/[id]
  - **Update imports**: Update the imports to use the new router API

## Case 6

**Prompt**: Upgrade the Next.js version from 11 to 12 and update the project configuration accordingly.

- Expected files: `package.json, tsconfig.json`
- Expected commands: `npm run build`
- Raw teacher file recall: `0.5`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.5`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `Next.js, package.json, next.config.js, .next.config.js`
- Commands: `npm install next@12 react@18 react-dom@18`
- Answer excerpt: Upgrading from Next.js 11 to 12 is a significant jump that involves changes to the file system structure (moving from `pages/` to `app/` or keeping `pages/` with specific constraints), dependency updates, and configuration adjustments. H...

**Memla in front**

- Prior trace ids: `2, 1, 6, 8`
- Plan files: `next.config.ts, next-env.d.ts, Next.js, src/server/routers/_app.ts, pnpm-lock.yaml, package.json`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `dependency_manifest, routing_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `next.config.ts, next-env.d.ts, Next.js, src/server/routers/_app.ts, pnpm-lock.yaml, package.json, next.config.js, tsconfig.json, package-lock.json`
- Combined commands: `npm run build, npm run lint, npm install, pnpm install`
- Answer excerpt: [Thought] The user wants to upgrade Next.js from version 11 to 12 and update the project configuration. Based on the retrieved memory, this is a known decision. I need to: 1. Update `package.json` to change the `next` dependency from `11...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update the TypeScript version from 4
  - 2, I will modify the `package
  - Here's the plan:
  - **Identify current version**: Check the current version of TypeScript in `package

## Case 7

**Prompt**: Update the Jest Playwright configuration to include artifact upload for e2e test videos.

- Expected files: `jest.playwright.config.ts`
- Expected commands: `npm run build, npm run lint`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `0.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `jest.config.js, jest.config.ts, playwright.config.ts`
- Commands: ``
- Answer excerpt: To add artifact upload for e2e test videos in your Jest Playwright configuration, we need to modify your `jest.config.js` (or `jest.config.ts`) to include the `testResultsProcessor` or `collectCoverageFrom` isn't the right place. Actuall...

**Memla in front**

- Prior trace ids: `8, 6, 5, 2`
- Plan files: `playwright/smoke.test.ts, src/server/routers/post.test.ts, pnpm-lock.yaml, src/server/routers/post.ts, src/pages/post/[id].tsx, src/server/routers/_app.ts`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `app_shell, dependency_manifest, routing_surface, service_boundary, state_holder, test_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `playwright/smoke.test.ts, src/server/routers/post.test.ts, pnpm-lock.yaml, src/server/routers/post.ts, src/pages/post/[id].tsx, src/server/routers/_app.ts, playwright.config.ts, playwright.config.js`
- Combined commands: `npm run build, npm run lint`
- Answer excerpt: [Thought] The user wants to update the Jest Playwright configuration to include artifact upload for e2e test videos. Based on the retrieved memory, this is a known decision. I need to: 1. Locate the Playwright configuration file (likely...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update the post detail page to use the new router API instead of the old one, I will modify the `src/pages/post/[id]
  - Here's the plan:
  - **Identify current usage**: Check the current usage of the old router API in `src/pages/post/[id]
  - **Update imports**: Update the imports to use the new router API

## Case 8

**Prompt**: Update all TrPC dependencies to version 9.0.1 in package.json.

- Expected files: `package.json`
- Expected commands: `npm run build`
- Raw teacher file recall: `1.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `package.json`
- Commands: `2. Run `npm install` or `yarn install` to install the updated packages`
- Answer excerpt: I'll help you update the TrPC dependencies to version 9.0.1 in your `package.json`. First, let me check your current `package.json` to see the existing TrPC dependencies: ```json { "dependencies": { "@trpc/client": "9.0.0", "@trpc/server...

**Memla in front**

- Prior trace ids: `1, 2, 8, 6`
- Plan files: `package.json, package-lock.json, src/pages/api/trpc/[trpc].ts, src/utils/trpc.ts, src/server/trpc.ts, src/server/routers/_app.ts`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `dependency_manifest, routing_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `package.json, package-lock.json, src/pages/api/trpc/[trpc].ts, src/utils/trpc.ts, src/server/trpc.ts, src/server/routers/_app.ts`
- Combined commands: `npm run build, npm run lint, npm install, pnpm install`
- Answer excerpt: [Thought] The user wants to update all tRPC dependencies to version 9.0.1 in `package.json`. Based on the retrieved memory, this is a known decision. I need to: 1. Open `package.json`. 2. Identify all tRPC-related dependencies (e.g., `@t...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update all tRPC dependencies to version 9
  - 0, I will modify the `package
  - Here's the plan:
  - **Identify current versions**: Check the current versions of tRPC packages in `package

## Case 9

**Prompt**: Update eslint-plugin-prettier to version 4.0.0 in package.json.

- Expected files: `package.json`
- Expected commands: `npm run build`
- Raw teacher file recall: `1.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `package.json`
- Commands: `2. Run `npm install` (or `yarn install`) to update the lockfile and install the new version.`
- Answer excerpt: To update `eslint-plugin-prettier` to version `4.0.0`, you need to modify the `package.json` file. ### Files to Modify - `package.json` ### Changes Required Locate the `devDependencies` (or `dependencies`, depending on your current setup...

**Memla in front**

- Prior trace ids: `1, 2, 8, 6`
- Plan files: `package.json, package-lock.json, eslint.config.mjs, src/server/routers/_app.ts, pnpm-lock.yaml, src/pages/post/[id].tsx`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `dependency_manifest, routing_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `package.json, package-lock.json, eslint.config.mjs, src/server/routers/_app.ts, pnpm-lock.yaml, src/pages/post/[id].tsx`
- Combined commands: `npm run build, npm run lint, npm install, pnpm install`
- Answer excerpt: [Thought] The user wants to update `eslint-plugin-prettier` to version `4.0.0` in `package.json`. Based on the retrieved memory, this is a known decision. I need to: 1. Open `package.json`. 2. Locate the `eslint-plugin-prettier` dependen...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update all tRPC dependencies to version 9
  - 0, I will modify the `package
  - Here's the plan:
  - **Identify current versions**: Check the current versions of tRPC packages in `package

## Case 10

**Prompt**: Update all TrPC dependencies to version 9.1.0 in package.json.

- Expected files: `package.json`
- Expected commands: `npm run build`
- Raw teacher file recall: `1.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `package.json`
- Commands: ``
- Answer excerpt: I'll help you update the TrPC dependencies to version 9.1.0 in your `package.json`. First, let me check your current `package.json` to see the existing TrPC dependencies: ```json { "dependencies": { "@trpc/client": "9.0.x", "@trpc/server...

**Memla in front**

- Prior trace ids: `1, 2, 8, 6`
- Plan files: `package.json, package-lock.json, src/pages/api/trpc/[trpc].ts, src/utils/trpc.ts, src/server/trpc.ts, src/server/routers/_app.ts`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `dependency_manifest, routing_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `package.json, package-lock.json, src/pages/api/trpc/[trpc].ts, src/utils/trpc.ts, src/server/trpc.ts, src/server/routers/_app.ts`
- Combined commands: `npm run build, npm run lint, npm install, pnpm install`
- Answer excerpt: [Thought] The user wants to update all tRPC dependencies to version `9.1.0` in `package.json`. Based on the retrieved memory, this is a known decision. I need to: 1. Open `package.json`. 2. Identify all tRPC-related dependencies (e.g., `...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update all tRPC dependencies to version 9
  - 0, I will modify the `package
  - Here's the plan:
  - **Identify current versions**: Check the current versions of tRPC packages in `package

## Case 11

**Prompt**: Update all TrPC dependencies from version 9.1.0 to 9.2.0 in package.json.

- Expected files: `package.json`
- Expected commands: `npm run build`
- Raw teacher file recall: `1.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `package.json`
- Commands: `npm install, npm test`
- Answer excerpt: I'll help you update the `@trpc/server` and related TrPC dependencies from version 9.1.0 to 9.2.0 in your `package.json`. First, let me check the current `package.json` to see the existing TrPC dependencies: ```bash cat package.json ```...

**Memla in front**

- Prior trace ids: `1, 2, 8, 6`
- Plan files: `package.json, package-lock.json, src/pages/api/trpc/[trpc].ts, src/utils/trpc.ts, src/server/trpc.ts, src/server/routers/_app.ts`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `dependency_manifest, routing_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `package.json, package-lock.json, src/pages/api/trpc/[trpc].ts, src/utils/trpc.ts, src/server/trpc.ts, src/server/routers/_app.ts`
- Combined commands: `npm run build, npm run lint, npm install, pnpm install`
- Answer excerpt: [Thought] The user wants to update all tRPC dependencies from version `9.1.0` to `9.2.0` in `package.json`. Based on the retrieved memory, this is a known decision. I need to: 1. Open `package.json`. 2. Identify all tRPC-related dependen...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update all tRPC dependencies to version 9
  - 0, I will modify the `package
  - Here's the plan:
  - **Identify current versions**: Check the current versions of tRPC packages in `package

## Case 12

**Prompt**: Update all project dependencies to their latest compatible versions.

- Expected files: `package.json`
- Expected commands: `npm run build`
- Raw teacher file recall: `1.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `package.json, requirements.txt, Cargo.toml, Node.js, package-lock.json`
- Commands: `pip install --upgrade -r requirements.txt`
- Answer excerpt: I can't automatically update all dependencies without knowing your specific project structure, package manager (npm, yarn, pip, etc.), and current `package.json`/`requirements.txt`/`Cargo.toml` contents. However, here's the safest, conve...

**Memla in front**

- Prior trace ids: `2, 1, 8, 6`
- Plan files: `src/server/routers/_app.ts, pnpm-lock.yaml, package.json, src/pages/post/[id].tsx, src/server/routers/post.ts, src/pages/index.tsx`
- Plan commands: `npm run build, npm run lint`
- Plan tests: `npm run build, npm run lint`
- Role targets: `dependency_manifest, routing_surface`
- Constraint tags: `dependency_upgrade, deployment_routing, verification_gate`
- Combined files: `src/server/routers/_app.ts, pnpm-lock.yaml, package.json, src/pages/post/[id].tsx, src/server/routers/post.ts, src/pages/index.tsx`
- Combined commands: `npm run build, npm run lint, npm install, pnpm install`
- Answer excerpt: [Thought] The user wants to update all project dependencies to their latest compatible versions. Based on the retrieved memory, this is a known decision. I need to: 1. Open `package.json`. 2. Identify all dependencies and devDependencies...
- Transmutations:
  - Trade strict server routing for client-side SPA fallback.
  - Trade stale dependency stability for updated compatibility plus verification.
- Patch steps:
  - To update the TypeScript version from 4
  - 2, I will modify the `package
  - Here's the plan:
  - **Identify current version**: Check the current version of TypeScript in `package

## Run It

```powershell
cd "C:\Users\samat\Project Memory\Project-Memory"
. .\.anthropic_env.ps1
py -3 -m memory_system.distillation.comparison_runner --db "distill\repo_curriculum_run_v1\trpc_next_prisma\curriculum.sqlite" --repo_root "..\external\trpc-examples-next-prisma-starter" --user_id default --teacher_model qwen3.5:9b --cases "distill\repo_curriculum_run_v1\trpc_next_prisma\unseen_cases.jsonl" --out_dir .\distill\head_to_head_demo
```
