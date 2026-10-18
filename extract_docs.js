const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const urlsFile = fs.readFileSync('docs_urls.txt', 'utf-8');
const urls = urlsFile.split('\n').map(u => u.trim()).filter(u => u.startsWith('http'));

async function extractPage(page, url) {
  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
    await page.waitForTimeout(1500);
    // Wait for main content
    await page.waitForSelector('article', { timeout: 15000 }).catch(() => {});
    
    const data = await page.evaluate(() => {
      const article = document.querySelector('article');
      const title = document.querySelector('h1')?.innerText?.trim() || document.title;
      let html = '';
      let text = '';
      if (article) {
        html = article.innerHTML;
        text = article.innerText.trim();
      }
      return { title, html, text };
    });
    
    return { url, success: true, ...data };
  } catch (err) {
    return { url, success: false, error: err.message };
  }
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  
  const results = [];
  for (const url of urls) {
    console.log(`Extracting: ${url}`);
    const result = await extractPage(page, url);
    results.push(result);
    console.log(`  -> ${result.success ? result.title : 'FAILED: ' + result.error}`);
  }
  
  await browser.close();
  
  fs.writeFileSync('extracted_pages.json', JSON.stringify(results, null, 2), 'utf-8');
  console.log(`\nDone. ${results.length} pages extracted.`);
})();
