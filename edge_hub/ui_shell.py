"""Shared presentation for the estate service desk; no operational side effects."""
import re

BRAND = '鄰伴智慧社區平台'


def service_shell(source):
    source = source.replace('__SERVICE_SHELL__', '__SERVICE_SHELL__<script src="/assets/service/ep-background.js" defer></script>')
    resident = 'data-service-area="resident"' in source
    logo = ('<span class="service-logo" aria-hidden="true"><svg viewBox="0 0 32 32" fill="none">'
            '<path d="M5 15 16 6l11 9v11H5Z" stroke="currentColor" stroke-width="2"/>'
            '<path d="M11 17h10m-10 5h6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>'
            '</svg></span><span>鄰伴<small>智慧社區平台</small></span>')
    if resident:
        privacy = re.search(r'<details class="resident-privacy-notice">[\s\S]*?</details>', source)
        notice = privacy[0] if privacy else ''
        if privacy:
            source = source.replace(notice, '', 1)
        return source.replace('__SERVICE_SHELL__',
            '<header class="resident-topbar"><a class="service-brand" href="/">'+logo+'</a>'
            '<div class="resident-topbar-actions">'+notice+
            '<a class="service-staff-link" href="/admin">職員入口</a></div></header>')
    links = [('/', '居民服務'), ('/admin', '管理工作台'), ('/robots', '機械人巡邏')]
    nav = ''.join(f'<a href="{href}">{label}</a>' for href, label in links)
    extra = ('<a class="service-case-link" href="/admin#caseHeading">居民求助 '
             '<span class="service-badge neutral" data-service-pending role="status">—</span></a>'
             '')
    shell = ('<a class="service-skip" href="#main-content">跳到主要內容</a>'
             '<header class="service-topbar"><a class="service-brand" href="/">'
             +logo+'</a>'
             f'<nav class="service-navigation" aria-label="鄰伴導航">{nav}</nav>{extra}</header>')
    return source.replace('__SERVICE_SHELL__', shell)
