with open('/Users/flavioc/Desktop/catalitium/app/views/templates/base.html', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace(
    '<form id="contactForm" class="mt-5 space-y-3">',
    '<form id="contactForm" method="post" action="{{ url_for(\'contact\') }}" class="mt-5 space-y-3">\n        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">'
).replace(
    '<form id="jobPostForm" class="mt-5 space-y-3">',
    '<form id="jobPostForm" method="post" action="{{ url_for(\'job_posting\') }}" class="mt-5 space-y-3">\n        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">'
).replace(
    '''  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/sw.js').catch(function(){});
      });
    }''',
    '''  <script>
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        var isLocal =
          window.location.hostname === 'localhost' ||
          window.location.hostname === '127.0.0.1';
        if (isLocal) {
          navigator.serviceWorker.getRegistrations().then(function(regs) {
            regs.forEach(function(reg) { reg.unregister(); });
          });
          if ('caches' in window) {
            caches.keys().then(function(keys) {
              keys.forEach(function(key) {
                if (key.indexOf('catalitium-') === 0) caches.delete(key);
              });
            });
          }
          return;
        }
        navigator.serviceWorker.register('/sw.js').catch(function(){});
      });
    }'''
).replace(
    "href=\"{{ url_for('static', filename='css/styles.css') }}\"",
    "href=\"{{ url_for('static', filename='css/styles.css', v=asset_version) }}\""
).replace(
    "href=\"{{ url_for('static', filename='js/main.js') }}\"",
    "href=\"{{ url_for('static', filename='js/main.js', v=asset_version) }}\""
).replace(
    "src=\"{{ url_for('static', filename='js/main.js') }}\"",
    "src=\"{{ url_for('static', filename='js/main.js', v=asset_version) }}\""
).replace(
    'crossorigin="anonymous"></script>',
    'crossorigin="anonymous" data-cookieconsent="marketing"></script>'
).replace(
    '<script>\n    window.dataLayer = window.dataLayer || [];',
    '<script {% if is_production_env %}data-cookieconsent="statistics"{% endif %}>\n    window.dataLayer = window.dataLayer || [];'
).replace(
    '''<form action="{{ url_for('subscribe') }}" method="post"
            class="mt-5 grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3">
        <input type="hidden" name="search_title"''',
'''<form action="{{ url_for('subscribe') }}" method="post"
            class="mt-5 grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-3">
        <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
        <input type="hidden" name="search_title"'''
).replace(
    '''  <style>
    {% if not is_production_env %}
    /* Local dev safety: avoid full-page dim if browser/extensions leave a dialog open. */
    dialog::backdrop {
      background: transparent !important;
      backdrop-filter: none !important;
    }
    {% endif %}''',
    '''  {% if not is_production_env %}
  <style>
    /* Local dev safety: avoid full-page dim if browser/extensions leave a dialog open. */
    dialog::backdrop {
      background: transparent !important;
      backdrop-filter: none !important;
    }
  </style>
  {% endif %}
  <style>'''
)

with open('/Users/flavioc/Desktop/catalitium/app/views/templates/base.html', 'w', encoding='utf-8') as f:
    f.write(content)
