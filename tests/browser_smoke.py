"""Optional real-browser workflow test; starts its own isolated local server.
Run: python tests/browser_smoke.py (after playwright install chromium).
"""
import io,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
import httpx
from PIL import Image
from playwright.sync_api import sync_playwright
repo=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
 with socket.socket() as sock:
  sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 url=f'http://127.0.0.1:{port}'
 proc=subprocess.Popen([sys.executable,'-m','astra_studio','--data',directory,'serve','--port',str(port)],cwd=repo,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 try:
  for _ in range(100):
   try:
    if httpx.get(url+'/api/capabilities').status_code==200:break
   except httpx.ConnectError:pass
   time.sleep(.1)
  with sync_playwright() as p:
   browser=p.chromium.launch();page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];page.on('pageerror',lambda error:errors.append(str(error)));page.goto(url)
   page.locator('#newProject').click();page.locator('#newName').fill('Browser smoke');page.locator('#createForm button.primary').click();page.wait_for_selector('.layerrow');assert page.locator('.layerrow').count()==15
   page.locator('.layerrow').first.click();buf=io.BytesIO();Image.new('RGBA',(64,32),'purple').save(buf,format='PNG');page.locator('#partFile').set_input_files({'name':'part.png','mimeType':'image/png','buffer':buf.getvalue()});page.wait_for_function("document.getElementById('revision').textContent.includes('버전 1')")
   old=page.locator('#x').input_value();page.locator('#x').fill('30');page.locator('#x').press('Tab');page.locator('#save').click();page.wait_for_function("document.getElementById('revision').textContent==='버전 2'")
   page.locator('#history').click();page.locator('#historyList button').filter(has_text='버전 1 ·').click();page.wait_for_function("document.getElementById('revision').textContent==='버전 3'");assert page.locator('#x').input_value()==old
   page.locator('#target').select_option('assemble');page.locator('#build').click();page.wait_for_function("document.getElementById('jobStatus').textContent.includes('completed')",timeout=30000);assert page.locator('#artifacts a').filter(has_text='layers.psd').count()==1
   page.set_viewport_size({'width':760,'height':1000});assert page.locator('#canvas').is_visible();assert not errors,errors;browser.close();print('PASS: create, upload, edit, save, restore, real PSD build, responsive view; zero JS errors')
 finally:
  proc.terminate();proc.wait(timeout=15)
