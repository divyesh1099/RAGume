import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

type PdfjsModule = {
  getDocument: (options: { url: string; disableWorker: boolean }) => { promise: Promise<any> };
};

function ensureRuntime(openResumeRoot: string) {
  const nodeModulesDir = path.join(openResumeRoot, "node_modules");
  const libSymlink = path.join(nodeModulesDir, "lib");
  const canvasDir = path.join(nodeModulesDir, "canvas");
  const canvasStub = path.join(canvasDir, "index.js");

  if (!fs.existsSync(nodeModulesDir)) {
    throw new Error(`OpenResume dependencies are missing at ${nodeModulesDir}. Run npm install first.`);
  }

  if (!fs.existsSync(libSymlink)) {
    fs.symlinkSync(path.join(openResumeRoot, "src/app/lib"), libSymlink, "dir");
  }

  if (!fs.existsSync(canvasStub)) {
    fs.mkdirSync(canvasDir, { recursive: true });
    fs.writeFileSync(canvasStub, "module.exports = {};\n", "utf8");
  }
}

async function importFromRoot<T>(openResumeRoot: string, relativePath: string): Promise<T> {
  const fileUrl = pathToFileURL(path.join(openResumeRoot, relativePath)).href;
  return (await import(fileUrl)) as T;
}

async function readPdfNode(pdfjs: PdfjsModule, resumePath: string) {
  const fileUrl = pathToFileURL(resumePath).href;
  const loadingTask = pdfjs.getDocument({ url: fileUrl, disableWorker: true });
  const pdfFile = await loadingTask.promise;
  let textItems: any[] = [];

  for (let pageNumber = 1; pageNumber <= pdfFile.numPages; pageNumber += 1) {
    const page = await pdfFile.getPage(pageNumber);
    const textContent = await page.getTextContent();
    await page.getOperatorList();
    const commonObjs = page.commonObjs;

    const pageTextItems = textContent.items.map((item: any) => {
      const text = String(item.str ?? "");
      const transform = Array.isArray(item.transform) ? item.transform : [0, 0, 0, 0, 0, 0];
      const pdfFontName = item.fontName;
      const nextItem: Record<string, unknown> = { ...item };

      delete nextItem.str;
      delete nextItem.dir;
      delete nextItem.transform;
      delete nextItem.fontName;

      let fontName = pdfFontName;
      try {
        const fontObj = commonObjs.get(pdfFontName as any);
        fontName = fontObj?.name || pdfFontName;
      } catch {
        fontName = pdfFontName;
      }

      return {
        ...nextItem,
        fontName,
        text: text.replace(/-­‐/g, "-"),
        x: transform[4] ?? 0,
        y: transform[5] ?? 0,
      };
    });

    textItems.push(...pageTextItems);
  }

  return textItems.filter((item) => !(item.hasEOL === false && String(item.text ?? "").trim() === ""));
}

async function main() {
  const resumePath = process.argv[2];
  if (!resumePath) {
    throw new Error("Usage: npx tsx scripts/openresume_bridge.ts <resume.pdf>");
  }

  const openResumeRoot = process.env.OPENRESUME_ROOT || "/tmp/open-resume";
  ensureRuntime(openResumeRoot);
  process.chdir(openResumeRoot);

  const pdfjs = await importFromRoot<PdfjsModule>(openResumeRoot, "node_modules/pdfjs-dist/legacy/build/pdf.js");
  const { groupTextItemsIntoLines } = await importFromRoot<any>(
    openResumeRoot,
    "src/app/lib/parse-resume-from-pdf/group-text-items-into-lines.ts",
  );
  const { groupLinesIntoSections } = await importFromRoot<any>(
    openResumeRoot,
    "src/app/lib/parse-resume-from-pdf/group-lines-into-sections.ts",
  );
  const { extractResumeFromSections } = await importFromRoot<any>(
    openResumeRoot,
    "src/app/lib/parse-resume-from-pdf/extract-resume-from-sections/index.ts",
  );

  const textItems = await readPdfNode(pdfjs, path.resolve(resumePath));
  const lines = groupTextItemsIntoLines(textItems);
  const sections = groupLinesIntoSections(lines);
  const resume = extractResumeFromSections(sections);

  console.log(
    JSON.stringify(
      {
        textItemCount: textItems.length,
        lineCount: lines.length,
        sectionKeys: Object.keys(sections),
        resume,
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
