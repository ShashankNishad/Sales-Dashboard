#!/usr/bin/env python
"""Fix escaped sequences in app.py HTML template."""

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace escaped quotes and braces
content = content.replace('\\"', '"')
content = content.replace('{{', '{')
content = content.replace('}}', '}')

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Fixed escaped sequences in HTML template')
