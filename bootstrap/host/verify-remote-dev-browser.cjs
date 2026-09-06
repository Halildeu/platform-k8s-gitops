// Real synthetic DEV browser login proof; does not assert every product journey.
if (require('os').hostname() !== 'stagingsw') throw new Error('Unexpected host');
const {chromium}=require('/srv/platform-dev/repos/platform-web/node_modules/@playwright/test');
const fs=require('fs');
(async()=>{
 const c=JSON.parse(fs.readFileSync('/srv/platform-dev/runtime/secrets/credentials.json','utf8'));
 const browser=await chromium.launch({headless:true});const page=await browser.newPage();
 const errors=[];page.on('pageerror',e=>errors.push(e.name));
 await page.goto('http://127.0.0.1:33000/',{waitUntil:'domcontentloaded',timeout:60000});
 await page.getByRole('link',{name:'Güvenli Kurumsal Giriş'}).click();
 await page.locator('#username').fill('developer');await page.locator('#password').fill(c.developer);
 await page.locator('#kc-login').click();
 await page.waitForURL('http://127.0.0.1:33000/**',{timeout:60000});
 await page.waitForTimeout(8000);
 const body=await page.locator('body').innerText();
 const result={url:page.url().split('?')[0].split('#')[0],loginReturned:true,bodyLength:body.length,pageErrorTypes:errors};
 await page.screenshot({path:'/srv/platform-dev/evidence/dev-login-browser.png',fullPage:true});
 fs.writeFileSync('/srv/platform-dev/evidence/dev-login-browser.json',JSON.stringify(result,null,2));
 console.log(JSON.stringify(result));
 await browser.close();
})().catch(e=>{console.error(e.name+': '+e.message.split('\n')[0]);process.exit(1)});
