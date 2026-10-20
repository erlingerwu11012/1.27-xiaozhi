const { chromium } = require("C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core");
const fs = require("fs");
const output = "C:/Users/Administrator/.codex/visualizations/2026/09/28/01a0e786-0843-7353-8440-53be6eae1529/";
(async () => {
  const browser = await chromium.launch({ headless:true, executablePath:"C:/Program Files/Google/Chrome/Application/chrome.exe" });
  const page = await browser.newPage({ viewport:{width:800,height:1050} });
  const errors=[];
  const rows=[];
  page.on("pageerror",e=>errors.push(e.message));
  await page.goto("file:///E:/github/github_code/all/4.30/tmp/context-memory-200k/prompt-memory-preview.html");
  const frame=page.frameLocator("iframe");
  await frame.locator("#prompt-memory-flow").waitFor();
  for(const viewport of [800,400,360]) {
    await page.setViewportSize({width:viewport,height:1050});
    for(const scene of ["prompt","search","compact","habit"]) {
      await frame.locator('[data-scene="'+scene+'"]').click();
      await page.waitForTimeout(120);
      const metrics=await frame.locator("#prompt-memory-flow").evaluate(root=>{
        const svg=root.querySelector("#pm-diagram svg");
        const view=svg.viewBox.baseVal;
        const outside=[...svg.querySelectorAll("text")].filter(text=>{
          const box=text.getBBox();
          return box.x < -1 || box.y < -1 || box.x+box.width>view.width+1 || box.y+box.height>view.height+1;
        }).map(text=>text.textContent);
        return {
          width:Math.round(root.getBoundingClientRect().width),
          height:Math.round(root.getBoundingClientRect().height),
          outside,
          selected:root.querySelector('[aria-pressed="true"]').dataset.scene,
          overflow:document.documentElement.scrollWidth>window.innerWidth+1
        };
      });
      rows.push({viewport,scene,...metrics});
      if(metrics.selected!==scene || metrics.outside.length || metrics.overflow) {
        throw new Error(JSON.stringify(rows[rows.length-1]));
      }
      if(viewport===800 || (viewport===360 && scene==="search")) {
        await frame.locator("#prompt-memory-flow").screenshot({path:output+"preview-"+scene+"-"+viewport+".png"});
      }
    }
  }
  await page.emulateMedia({colorScheme:"dark"});
  await page.setViewportSize({width:800,height:1050});
  await frame.locator('[data-scene="compact"]').click();
  await frame.locator("#prompt-memory-flow").screenshot({path:output+"preview-dark.png"});
  await browser.close();
  if(errors.length) throw new Error(JSON.stringify(errors));
  fs.writeFileSync(output+"preview-check.json",JSON.stringify({checks:rows,errors},null,2));
  process.stdout.write(JSON.stringify({scenarios:rows.length,errors:errors.length,outside:0,overflow:0}));
})().catch(error=>{console.error(error);process.exit(1);});
