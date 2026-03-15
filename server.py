#!/usr/bin/env python3
"""
网页抓取助手 - 后端服务器
支持微信公众号、知乎、Twitter/X、普通网页的内容抓取和图片下载
"""

import os
import re
import json
import subprocess
import platform
from datetime import datetime
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup

# Playwright 支持
PLAYWRIGHT_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    pass

app = Flask(__name__)
CORS(app)

# 配置
DEFAULT_SAVE_PATH = os.path.expanduser("~/Downloads/web-scraper")
USER_CONFIG_PATH = os.path.expanduser("~/.web-scraper-config.json")

# 需要使用 Playwright 的网站（动态渲染/反爬虫机制）
DYNAMIC_SITES = ['twitter.com', 'x.com', 'facebook.com', 'instagram.com', 'tiktok.com', 'zhihu.com', '42plugin.com']

# 需要特殊 headers 的网站
SPECIAL_HEADERS = {
    'zhihu.com': {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Cookie': '_xsrf=auto; d_c0=auto',
        'Referer': 'https://www.zhihu.com/',
    },
    'mp.weixin.qq.com': {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://mp.weixin.qq.com/',
    }
}

def load_config():
    if os.path.exists(USER_CONFIG_PATH):
        try:
            with open(USER_CONFIG_PATH, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}

def save_config(config):
    with open(USER_CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)

def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = name.strip('. ')
    if len(name) > 100:
        name = name[:100]
    if not name:
        name = datetime.now().strftime('%Y%m%d_%H%M%S')
    return name

def get_domain(url):
    domain = urlparse(url).netloc.lower()
    return domain.replace('www.', '')

def needs_playwright(url):
    domain = get_domain(url)
    return any(site in domain for site in DYNAMIC_SITES)

def get_special_headers(url):
    domain = get_domain(url)
    for site, headers in SPECIAL_HEADERS.items():
        if site in domain:
            return headers
    return None

def fetch_page_static(url):
    special_headers = get_special_headers(url)
    if special_headers:
        headers = special_headers
    else:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    if response.encoding.lower() in ['iso-8859-1', 'latin-1']:
        content = response.content
        for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030']:
            try:
                return content.decode(encoding)
            except:
                continue
        return content.decode('utf-8', errors='ignore')
    return response.text

def fetch_page_dynamic(url):
    if not PLAYWRIGHT_AVAILABLE:
        raise Exception("Playwright 未安装")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        page = context.new_page()
        try:
            page.goto(url, wait_until='networkidle', timeout=60000)
            page.wait_for_timeout(3000)
            # 滚动页面以触发懒加载
            for _ in range(3):
                page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                page.wait_for_timeout(1000)
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(1000)
            if 'twitter.com' in url or 'x.com' in url:
                try:
                    page.wait_for_selector('article[data-testid="tweet"]', timeout=10000)
                except:
                    pass
                page.wait_for_timeout(2000)
            html = page.content()
        finally:
            browser.close()
        return html

def fetch_page(url):
    if needs_playwright(url) and PLAYWRIGHT_AVAILABLE:
        return fetch_page_dynamic(url)
    else:
        return fetch_page_static(url)

def extract_content(url, html):
    soup = BeautifulSoup(html, 'html.parser')
    title = None
    domain = get_domain(url)

    # 知乎特殊处理
    if 'zhihu.com' in domain:
        question_title = soup.find('h1', class_='QuestionHeader-title')
        if question_title:
            title = question_title.get_text(strip=True)
        if not title:
            og_title = soup.find('meta', property='og:title')
            if og_title:
                title = og_title.get('content')

    # Twitter/X
    if 'twitter.com' in domain or 'x.com' in domain:
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content')
        if not title:
            match = re.search(r'(twitter\.com|x\.com)/([^/]+)', url)
            if match:
                title = f"Twitter - @{match.group(2)}"

    # 微信公众号
    if 'mp.weixin.qq.com' in domain:
        meta_title = soup.find('meta', property='og:title')
        if meta_title:
            title = meta_title.get('content')
        if not title:
            title_tag = soup.find('h1', class_='rich_media_title')
            if title_tag:
                title = title_tag.get_text(strip=True)

    # 通用标题
    if not title:
        og_title = soup.find('meta', property='og:title')
        if og_title:
            title = og_title.get('content')

    if not title:
        title_tag = soup.find('title')
        if title_tag:
            title = title_tag.get_text(strip=True)

    if not title:
        title = "未命名文档"

    title = sanitize_filename(title)

    # 提取内容区域
    content_area = None

    # 知乎
    if 'zhihu.com' in domain:
        answer = soup.find('div', class_='RichContent-inner')
        if answer:
            content_area = answer
        else:
            question_detail = soup.find('div', class_='QuestionRichText')
            if question_detail:
                content_area = question_detail
        if not content_area:
            content_area = soup.find('div', class_='Post-RichText')
        if not content_area:
            content_area = soup.find('article')

    # Twitter
    if not content_area and ('twitter.com' in domain or 'x.com' in domain):
        tweets = soup.find_all('article')
        if tweets:
            content_area = soup.new_tag('div')
            for tweet in tweets:
                content_area.append(tweet)

    # 微信公众号
    if not content_area and 'mp.weixin.qq.com' in domain:
        content_area = soup.find('div', class_='rich_media_content')
        if not content_area:
            content_area = soup.find('div', id='js_content')

    # 通用
    if not content_area:
        for selector in ['article', '[role="main"]', '.content', '.article', '.post', '.entry-content', 'main']:
            content_area = soup.select_one(selector)
            if content_area:
                break

    if not content_area:
        content_area = soup.find('body')

    # 提取图片
    images = []
    if content_area:
        for i, img in enumerate(content_area.find_all('img')):
            src = img.get('src') or img.get('data-src') or img.get('data-original') or img.get('data-actualsrc')
            if src:
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = urljoin(url, src)
                elif not src.startswith('http'):
                    src = urljoin(url, src)
                # 过滤
                if any(x in src for x in ['emoji', 'emotion', 'smiley', 'icon', 'loading', 'placeholder', 'avatar', 'profile_image', 'zhimg.com/80/']):
                    continue
                alt = img.get('alt', '')
                images.append({'url': src, 'alt': alt, 'index': i})

    # 元数据
    metadata = {
        'title': title,
        'url': url,
        'domain': urlparse(url).netloc,
        'fetch_time': datetime.now().isoformat()
    }

    desc = soup.find('meta', attrs={'name': 'description'})
    if desc:
        metadata['description'] = desc.get('content', '')

    og_desc = soup.find('meta', property='og:description')
    if og_desc and not metadata.get('description'):
        metadata['description'] = og_desc.get('content', '')

    return {
        'title': title,
        'content_html': str(content_area) if content_area else '',
        'images': images,
        'metadata': metadata
    }

def html_to_markdown(html_content, images, base_url, image_folder):
    soup = BeautifulSoup(html_content, 'html.parser')
    for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'noscript']):
        tag.decompose()
    for img in soup.find_all('img'):
        src = img.get('src') or img.get('data-src') or img.get('data-original') or img.get('data-actualsrc')
        if src:
            img_info = None
            for info in images:
                if info['url'] == src or src in info['url'] or info['url'] in src:
                    img_info = info
                    break
            if img_info:
                local_name = img_info.get('local_name', 'image.jpg')
                img.replace_with(f'![{img_info.get("alt", "")}](./{image_folder}/{local_name})')
            else:
                img.replace_with(f'![]({src})')
    for i in range(6, 0, -1):
        for h in soup.find_all(f'h{i}'):
            h.string = '#' * i + ' ' + h.get_text(strip=True) + '\n\n'
    for p in soup.find_all('p'):
        text = p.get_text(strip=True)
        if text:
            p.string = text + '\n\n'
    for br in soup.find_all('br'):
        br.replace_with('\n')
    for li in soup.find_all('li'):
        text = li.get_text(strip=True)
        if text:
            li.string = '- ' + text + '\n'
    for a in soup.find_all('a'):
        text = a.get_text(strip=True)
        href = a.get('href', '')
        if text and href and href.startswith('http'):
            a.replace_with(f'[{text}]({href})')
    text = soup.get_text()
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = text.strip()
    return text

def download_image(url, save_path, headers):
    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        with open(save_path, 'wb') as f:
            f.write(response.content)
        return True
    except Exception as e:
        print(f"下载图片失败: {e}")
        return False

def generate_image_filename(url, index, image_format='original'):
    parsed = urlparse(url)
    path = unquote(parsed.path)
    ext = os.path.splitext(path)[1]
    if not ext or ext.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']:
        ext = '.jpg'
    return f"{str(index + 1).zfill(2)}{ext}"

@app.route('/api/config', methods=['GET'])
def get_config():
    config = load_config()
    return jsonify({
        'success': True,
        'defaultSavePath': DEFAULT_SAVE_PATH,
        'savePath': config.get('savePath', DEFAULT_SAVE_PATH),
        'apiServer': request.host_url.rstrip('/'),
        'playwrightAvailable': PLAYWRIGHT_AVAILABLE
    })

@app.route('/api/config', methods=['POST'])
def update_config():
    data = request.json
    config = load_config()
    config.update(data)
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/preview', methods=['POST'])
def preview():
    data = request.json
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'success': False, 'error': '请输入URL'})
    try:
        html = fetch_page(url)
        result = extract_content(url, html)
        soup = BeautifulSoup(result['content_html'], 'html.parser')
        text = soup.get_text(separator='\n')
        text = re.sub(r'\n{3,}', '\n\n', text)
        return jsonify({
            'success': True,
            'title': result['title'],
            'content': text[:5000],
            'images': result['images'][:20]
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/scrape', methods=['POST'])
def scrape():
    data = request.json
    url = data.get('url', '').strip()
    options = data.get('options', {})
    if not url:
        return jsonify({'success': False, 'error': '请输入URL'})
    try:
        html = fetch_page(url)
        result = extract_content(url, html)
        save_path = options.get('savePath', DEFAULT_SAVE_PATH)
        save_path = os.path.expanduser(save_path)
        title = result['title']
        main_folder = os.path.join(save_path, title)
        os.makedirs(main_folder, exist_ok=True)
        image_folder_name = options.get('imageFolder', 'images')
        if image_folder_name != 'same':
            image_folder = os.path.join(main_folder, image_folder_name)
        else:
            image_folder = main_folder
        if result['images'] and options.get('downloadImages', True):
            os.makedirs(image_folder, exist_ok=True)
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
            'Referer': url
        }
        downloaded_images = []
        for i, img in enumerate(result['images']):
            img_url = img['url']
            filename = generate_image_filename(img_url, i, options.get('imageFormat', 'original'))
            img['local_name'] = filename
            local_path = os.path.join(image_folder, filename)
            if download_image(img_url, local_path, headers):
                downloaded_images.append(img)
                img['local_path'] = local_path
        markdown = html_to_markdown(
            result['content_html'],
            downloaded_images,
            url,
            image_folder_name
        )
        if options.get('includeMetadata', True):
            metadata = result['metadata']
            header = f"""# {metadata['title']}

> 来源: [{metadata['domain']}]({metadata['url']})
> 抓取时间: {metadata['fetch_time']}
"""
            if metadata.get('description'):
                desc = metadata['description'][:200]
                header += f"> 描述: {desc}\n"
            header += "\n---\n\n"
            markdown = header + markdown
        md_filename = f"{title}.md"
        md_path = os.path.join(main_folder, md_filename)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown)
        return jsonify({
            'success': True,
            'title': title,
            'filePath': md_path,
            'folderPath': main_folder,
            'imageCount': len(downloaded_images)
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/open-folder', methods=['POST'])
def open_folder():
    data = request.json
    path = data.get('path', '')
    if not path or not os.path.exists(path):
        return jsonify({'success': False, 'error': '路径不存在'})
    try:
        system = platform.system()
        if system == 'Darwin':
            subprocess.run(['open', path])
        elif system == 'Windows':
            subprocess.run(['explorer', path])
        else:
            subprocess.run(['xdg-open', path])
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/browse-folder', methods=['GET'])
def browse_folder():
    path = request.args.get('path', os.path.expanduser('~'))
    if not os.path.exists(path):
        path = os.path.expanduser('~')
    try:
        items = []
        for item in os.listdir(path):
            full_path = os.path.join(path, item)
            if os.path.isdir(full_path):
                items.append({'name': item, 'path': full_path, 'type': 'folder'})
        items.sort(key=lambda x: x['name'].lower())
        return jsonify({
            'success': True,
            'currentPath': path,
            'parentPath': os.path.dirname(path),
            'items': items
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/')
def index():
    return send_from_directory('.', 'web-scraper-app.html')

if __name__ == '__main__':
    print("=" * 50)
    print("网页抓取助手 - Web Scraper")
    print("=" * 50)
    print(f"默认保存路径: {DEFAULT_SAVE_PATH}")
    print(f"Playwright 支持: {'已启用' if PLAYWRIGHT_AVAILABLE else '未安装'}")
    print("请在浏览器中打开: http://localhost:5555")
    print("=" * 50)
    app.run(host='127.0.0.1', port=5555, debug=False)
