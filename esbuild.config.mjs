import { build } from 'esbuild';
import { readFileSync, mkdirSync, existsSync, readdirSync } from 'fs';
import { join, resolve } from 'path';

const ROOT = resolve(import.meta.dirname || '.');
const STATIC = join(ROOT, 'web', 'static');
const DIST = join(STATIC, 'dist');

const isProd = process.argv.includes('--prod');
const isWatch = process.argv.includes('--watch');

// ─────────────────────────────────────────────────────────────
// JS files in exact load order (matches index.html)
// core.js first, init.js last — order matters for globals
// ─────────────────────────────────────────────────────────────
const JS_ORDER = [
  'core.js',
  'projects.js',
  'companies.js',
  'entities.js',
  'taxonomy.js',
  'maps.js',
  'processing.js',
  'filters.js',
  'tags.js',
  'research.js',
  'presentation.js',
  'canvas.js',
  'diagram.js',
  'ai.js',
  'export.js',
  'settings.js',
  'keyboard.js',
  'sse.js',
  'charts.js',
  'app-settings.js',
  'integrations.js',
  'dimensions.js',
  'discovery.js',
  'review.js',
  'features.js',
  'capture.js',
  'lenses.js',
  'reports.js',
  'monitoring.js',
  'insights.js',
  'playbooks.js',
  'crossproject.js',
  'provenance.js',
  'init.js',
];

// ─────────────────────────────────────────────────────────────
// CSS files to bundle
// Root-level CSS in explicit order (was previously @import'd by styles.css,
// but @import breaks when bundled — files must be inlined directly).
// Then component CSS from web/static/css/ (alphabetical).
// print.css excluded — loaded separately with media="print".
// ─────────────────────────────────────────────────────────────
const CSS_ROOT_ORDER = [
  'base.css',
  'layout.css',
  'companies.css',
  'taxonomy.css',
  'processing.css',
  'maps.css',
  'reports.css',
  'social.css',
  'canvas.css',
  'integrations.css',
  'views.css',
  'presentation.css',
  'app-settings.css',
  'dimensions.css',
  'discovery.css',
];

const CSS_FILES = [
  // Root-level CSS files (order matches former styles.css @imports)
  ...CSS_ROOT_ORDER.map(f => join(STATIC, f)),
  // Then component CSS (from web/static/css/)
  ...getCssFiles(),
];

function getCssFiles() {
  const cssDir = join(STATIC, 'css');
  if (!existsSync(cssDir)) return [];
  return readdirSync(cssDir)
    .filter(f => f.endsWith('.css') && f !== 'print.css')
    .sort()
    .map(f => join(cssDir, f));
}

// ─────────────────────────────────────────────────────────────
// Concatenate JS files (they use globals, not ES modules)
// ─────────────────────────────────────────────────────────────
function concatJS() {
  const jsDir = join(STATIC, 'js');
  const parts = [];
  for (const file of JS_ORDER) {
    const filePath = join(jsDir, file);
    if (!existsSync(filePath)) {
      console.warn(`  Warning: ${file} not found, skipping`);
      continue;
    }
    parts.push(`// ── ${file} ──`);
    parts.push(readFileSync(filePath, 'utf8'));
    parts.push(''); // blank line separator
  }
  return parts.join('\n');
}

// ─────────────────────────────────────────────────────────────
// Concatenate CSS files
// ─────────────────────────────────────────────────────────────
function concatCSS() {
  const parts = [];
  for (const filePath of CSS_FILES) {
    if (!existsSync(filePath)) {
      console.warn(`  Warning: ${filePath} not found, skipping`);
      continue;
    }
    const name = filePath.replace(STATIC + '/', '');
    parts.push(`/* ── ${name} ── */`);
    parts.push(readFileSync(filePath, 'utf8'));
    parts.push(''); // blank line separator
  }
  return parts.join('\n');
}

// ─────────────────────────────────────────────────────────────
// Build
// ─────────────────────────────────────────────────────────────
async function runBuild() {
  mkdirSync(DIST, { recursive: true });

  const mode = isProd ? 'production' : 'development';
  console.log(`\nBuilding bundles (${mode})...\n`);

  // ── JS Bundle ──
  const jsContent = concatJS();
  await build({
    stdin: {
      contents: jsContent,
      loader: 'js',
    },
    outfile: join(DIST, 'app.bundle.js'),
    bundle: false,
    minify: isProd,
    sourcemap: !isProd,
    target: ['es2020'],
    charset: 'utf8',
    logLevel: 'info',
  });

  // ── CSS Bundle ──
  const cssContent = concatCSS();
  await build({
    stdin: {
      contents: cssContent,
      loader: 'css',
    },
    outfile: join(DIST, 'app.bundle.css'),
    bundle: false,
    minify: isProd,
    sourcemap: !isProd,
    target: ['es2020'],
    charset: 'utf8',
    logLevel: 'info',
  });

  const jsSize = readFileSync(join(DIST, 'app.bundle.js')).length;
  const cssSize = readFileSync(join(DIST, 'app.bundle.css')).length;
  console.log(`\n  JS bundle:  ${(jsSize / 1024).toFixed(1)} KB`);
  console.log(`  CSS bundle: ${(cssSize / 1024).toFixed(1)} KB`);
  console.log(`  Mode:       ${mode}`);
  console.log(`  Sourcemaps: ${!isProd}\n`);
}

// ─────────────────────────────────────────────────────────────
// Watch mode: rebuild on file changes
// ─────────────────────────────────────────────────────────────
if (isWatch) {
  const { watch: fsWatch } = await import('fs');
  console.log('Watch mode enabled — rebuilding on changes...\n');

  await runBuild();

  const watchDirs = [join(STATIC, 'js'), join(STATIC, 'css')];
  // Also watch root-level CSS files
  const watchFiles = CSS_ROOT_ORDER.map(f => join(STATIC, f));

  for (const dir of watchDirs) {
    fsWatch(dir, { recursive: true }, async (eventType, filename) => {
      if (!filename || !filename.endsWith('.js') && !filename.endsWith('.css')) return;
      console.log(`\n  Changed: ${filename}`);
      try {
        await runBuild();
      } catch (e) {
        console.error('Build error:', e.message);
      }
    });
  }
  for (const file of watchFiles) {
    fsWatch(file, async () => {
      console.log(`\n  Changed: styles.css`);
      try {
        await runBuild();
      } catch (e) {
        console.error('Build error:', e.message);
      }
    });
  }
} else {
  await runBuild();
}
