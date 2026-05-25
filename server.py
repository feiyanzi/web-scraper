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
import time
from datetime import datetime
from urllib.parse import urljoin, urlparse, unquote
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import requests
from requests.exceptions import ConnectionError, Timeout, RequestException
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

# 政府网站（需要特殊处理）
GOV_SITES = ['gov.cn', 'sc.gov.cn', 'people.com.cn', 'xinhuanet.com']

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
    },
    'gov.cn': {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
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

def fetch_page_static(url, max_retries=3):
    """获取网页内容，支持重试机制"""
    special_headers = get_special_headers(url)
    if special_headers:
        headers = special_headers
    else:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }

    last_error = None
    for attempt in range(max_retries):
        try:
            # 指数退避
            if attempt > 0:
                wait_time = 2 ** attempt  # 2, 4, 8 秒
                time.sleep(wait_time)

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

        except (ConnectionError, ConnectionResetError) as e:
            last_error = e
            print(f"连接错误 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                print(f"等待 {2 ** (attempt + 1)} 秒后重试...")
                continue
        except Timeout as e:
            last_error = e
            print(f"请求超时 (尝试 {attempt + 1}/{max_retries}): {e}")
            if attempt < max_retries - 1:
                continue
        except RequestException as e:
            last_error = e
            print(f"请求错误: {e}")
            break

    raise Exception(f"获取页面失败（重试{max_retries}次后）: {last_error}")

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
            # 微信公众号特殊处理
            if 'mp.weixin.qq.com' in url:
                try:
                    page.wait_for_selector('#js_content, .rich_media_content', timeout=15000)
                except:
                    pass
                page.wait_for_timeout(3000)
            html = page.content()
        finally:
            browser.close()
        return html

def is_gov_site(url):
    """检查是否为政府网站"""
    domain = get_domain(url)
    return any(site in domain for site in GOV_SITES)

def fetch_page(url):
    """获取页面，自动选择最佳方式"""
    # 政府网站优先使用 Playwright（如果可用）
    if is_gov_site(url) and PLAYWRIGHT_AVAILABLE:
        try:
            print(f"检测到政府网站，使用 Playwright 获取: {url}")
            return fetch_page_dynamic(url)
        except Exception as e:
            print(f"Playwright 获取失败，回退到静态方式: {e}")
            return fetch_page_static(url, max_retries=3)
    elif needs_playwright(url) and PLAYWRIGHT_AVAILABLE:
        return fetch_page_dynamic(url)
    else:
        return fetch_page_static(url)

def is_twitter_url(url):
    """检查是否为 Twitter/X 链接"""
    domain = get_domain(url)
    return 'twitter.com' in domain or 'x.com' in domain

def extract_tweet_id(url):
    """从 Twitter/X URL 中提取推文 ID"""
    # 匹配格式: twitter.com/username/status/1234567890 或 x.com/username/status/1234567890
    match = re.search(r'(?:twitter\.com|x\.com)/\w+/status/(\d+)', url)
    if match:
        return match.group(1)
    return None

def fetch_tweet_via_fxtwitter(url):
    """使用 fxtwitter API 获取推文数据"""
    tweet_id = extract_tweet_id(url)
    if not tweet_id:
        return None

    try:
        # fxtwitter API 格式: https://api.fxtwitter.com/status/:tweet_id
        api_url = f"https://api.fxtwitter.com/status/{tweet_id}"
        print(f"使用 fxtwitter API 获取推文: {api_url}")

        response = requests.get(api_url, timeout=15)
        response.raise_for_status()
        data = response.json()

        if data.get('code') == 200 and data.get('tweet'):
            return data
        else:
            print(f"fxtwitter API 返回错误: {data}")
            return None
    except Exception as e:
        print(f"fxtwitter API 请求失败: {e}")
        return None

def twitter_article_to_markdown(tweet_data):
    """将 Twitter Article 内容转换为 Markdown"""
    tweet = tweet_data.get('tweet', {})
    article = tweet.get('article', {})

    if not article:
        # 普通推文，返回文本内容
        text = tweet.get('text', '')
        return text, [], tweet.get('media', {}).get('photos', [])

    # 处理 Article 内容
    blocks = article.get('content', {}).get('blocks', [])
    entity_map_raw = article.get('content', {}).get('entityMap', [])

    # 将 entityMap 列表转换为字典
    entity_map = {}
    if isinstance(entity_map_raw, list):
        for item in entity_map_raw:
            if isinstance(item, dict) and 'key' in item:
                entity_map[item['key']] = item.get('value', {})
    elif isinstance(entity_map_raw, dict):
        entity_map = entity_map_raw

    lines = []
    images = []

    for block in blocks:
        text = block.get('text', '')
        block_type = block.get('type', 'unstyled')
        styles = block.get('inlineStyleRanges', [])
        entities = block.get('entityRanges', [])

        # 处理样式
        if styles:
            # 按 offset 排序，从后往前处理以避免 offset 变化
            sorted_styles = sorted(styles, key=lambda x: x['offset'], reverse=True)
            for style in sorted_styles:
                offset = style['offset']
                length = style['length']
                style_type = style['style']
                if style_type == 'Bold':
                    text = text[:offset] + '**' + text[offset:offset+length] + '**' + text[offset+length:]
                elif style_type == 'Italic':
                    text = text[:offset] + '*' + text[offset:offset+length] + '*' + text[offset+length:]

        # 处理链接
        if entities:
            sorted_entities = sorted(entities, key=lambda x: x['offset'], reverse=True)
            for entity in sorted_entities:
                offset = entity['offset']
                length = entity['length']
                key = entity.get('key')
                entity_data = entity_map.get(str(key), {})
                if entity_data.get('type') == 'LINK':
                    url = entity_data.get('data', {}).get('url', '')
                    text = text[:offset] + f'[{text[offset:offset+length]}]({url})' + text[offset+length:]

        # 根据类型添加 Markdown 格式
        if block_type == 'blockquote':
            lines.append(f'> {text}')
        elif block_type == 'header-one':
            lines.append(f'# {text}')
        elif block_type == 'header-two':
            lines.append(f'## {text}')
        elif block_type == 'code-block':
            lines.append(f'```\n{text}\n```')
        elif block_type == 'unordered-list-item':
            lines.append(f'- {text}')
        elif block_type == 'ordered-list-item':
            lines.append(f'1. {text}')
        else:
            if text:  # 只添加非空行
                lines.append(text)

    # 获取封面图片
    cover = article.get('cover_media', {})
    if cover and cover.get('media_info', {}).get('original_img_url'):
        images.append({
            'url': cover['media_info']['original_img_url'],
            'type': 'cover'
        })

    # 获取文章内嵌图片（从 media_entities）
    media_entities = article.get('media_entities', [])
    for entity in media_entities:
        media_info = entity.get('media_info', {})
        img_url = media_info.get('original_img_url')
        if img_url:
            images.append({
                'url': img_url,
                'type': 'article',
                'media_id': entity.get('media_id'),
                'width': media_info.get('original_img_width'),
                'height': media_info.get('original_img_height')
            })

    # 获取推文中的图片
    photos = tweet.get('media', {}).get('photos', [])

    return '\n\n'.join(lines), images, photos

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

    # 检测微信公众号验证页面 - 只检查可见文本中的验证提示
    if 'mp.weixin.qq.com' in domain and content_area:
        page_text = content_area.get_text(strip=True)
        # 只检查页面上实际显示的验证相关文字，避免误判
        verification_keywords = ['环境异常', '完成验证', '请完成安全验证', '访问过于频繁', '系统检测到异常']
        is_verification_page = any(keyword in page_text for keyword in verification_keywords)
        # 额外检查：如果内容区域几乎没有实际内容，可能是验证页
        if not is_verification_page and len(page_text) < 100:
            # 检查是否有验证相关的HTML结构
            verify_div = soup.find('div', class_=lambda x: x and ('verify' in x.lower() or 'captcha' in x.lower()))
            if verify_div:
                is_verification_page = True
        if is_verification_page:
            raise Exception('微信公众号需要验证，请在微信中打开此链接后再试。微信公众号有严格的反爬机制，建议直接在微信中查看文章。')

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

        # Twitter/X 特殊处理：使用 fxtwitter API 获取完整 JSON 数据
        tweet_json_data = None
        if is_twitter_url(url):
            print(f"检测到 Twitter/X 链接，使用 fxtwitter API 获取数据...")
            tweet_json_data = fetch_tweet_via_fxtwitter(url)
            if tweet_json_data:
                # 保存完整的 JSON 数据
                json_filename = f"{title}_tweet.json"
                json_path = os.path.join(main_folder, json_filename)
                with open(json_path, 'w', encoding='utf-8') as f:
                    json.dump(tweet_json_data, f, ensure_ascii=False, indent=2)
                print(f"已保存推文 JSON 数据: {json_path}")

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

        # 如果是 Twitter 且有 fxtwitter 数据，优先使用其图片 URL
        if tweet_json_data and tweet_json_data.get('tweet', {}).get('media', {}).get('photos'):
            photos = tweet_json_data['tweet']['media']['photos']
            for i, photo in enumerate(photos):
                img_url = photo.get('url')
                if img_url:
                    # 获取最高质量的图片
                    if '?' in img_url:
                        img_url = img_url.split('?')[0]
                    img_url = img_url + '?name=orig'
                    filename = generate_image_filename(img_url, i, options.get('imageFormat', 'original'))
                    local_path = os.path.join(image_folder, filename)
                    if download_image(img_url, local_path, headers):
                        downloaded_images.append({
                            'url': img_url,
                            'local_name': filename,
                            'local_path': local_path
                        })

        # 下载其他图片（非 Twitter 或 fxtwitter 失败时）
        if not downloaded_images:
            for i, img in enumerate(result['images']):
                img_url = img['url']
                filename = generate_image_filename(img_url, i, options.get('imageFormat', 'original'))
                img['local_name'] = filename
                local_path = os.path.join(image_folder, filename)
                if download_image(img_url, local_path, headers):
                    downloaded_images.append(img)
                    img['local_path'] = local_path

        # 生成 Markdown 内容
        # 如果是 Twitter Article，使用 fxtwitter 数据
        if tweet_json_data and tweet_json_data.get('tweet', {}).get('article'):
            article_markdown, article_images, photos = twitter_article_to_markdown(tweet_json_data)
            markdown = article_markdown

            # 使用文章标题
            article_title = tweet_json_data['tweet']['article'].get('title', title)
            if article_title:
                title = article_title

            # 重命名文件夹（如果标题不同）
            new_main_folder = os.path.join(save_path, sanitize_filename(title))
            if new_main_folder != main_folder:
                import shutil
                # 如果新文件夹已存在，先删除
                if os.path.exists(new_main_folder):
                    shutil.rmtree(new_main_folder)
                shutil.move(main_folder, new_main_folder)
                main_folder = new_main_folder
                # 更新图片文件夹路径
                if image_folder_name != 'same':
                    image_folder = os.path.join(main_folder, image_folder_name)
                else:
                    image_folder = main_folder

            # 下载文章图片（封面 + 内嵌图片）
            if article_images and options.get('downloadImages', True):
                os.makedirs(image_folder, exist_ok=True)
                for i, img in enumerate(article_images):
                    img_url = img.get('url')
                    if img_url:
                        # 获取最高质量图片
                        if '?' in img_url:
                            img_url = img_url.split('?')[0]
                        img_url = img_url + '?name=orig'
                        filename = generate_image_filename(img_url, len(downloaded_images), options.get('imageFormat', 'original'))
                        local_path = os.path.join(image_folder, filename)
                        if download_image(img_url, local_path, headers):
                            downloaded_images.append({
                                'url': img_url,
                                'local_name': filename,
                                'local_path': local_path,
                                'type': img.get('type', 'article')
                            })
        else:
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
            # 如果有 fxtwitter 数据，添加额外信息
            if tweet_json_data and tweet_json_data.get('tweet'):
                tweet = tweet_json_data['tweet']
                if tweet.get('author', {}).get('name'):
                    header += f"> 作者: {tweet['author']['name']} (@{tweet['author'].get('screen_name', '')})\n"
                if tweet.get('likes'):
                    header += f"> 点赞: {tweet['likes']}\n"
                if tweet.get('retweets'):
                    header += f"> 转发: {tweet['retweets']}\n"
                if tweet.get('replies'):
                    header += f"> 回复: {tweet['replies']}\n"
            header += "\n---\n\n"
            markdown = header + markdown
        md_filename = f"{title}.md"
        md_path = os.path.join(main_folder, md_filename)
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(markdown)

        response = {
            'success': True,
            'title': title,
            'filePath': md_path,
            'folderPath': main_folder,
            'imageCount': len(downloaded_images)
        }
        if tweet_json_data:
            response['tweetData'] = True
            response['tweetJsonPath'] = os.path.join(main_folder, f"{title}_tweet.json")

        return jsonify(response)
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
            # 过滤隐藏文件夹（以.开头的文件夹）
            if item.startswith('.'):
                continue
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
