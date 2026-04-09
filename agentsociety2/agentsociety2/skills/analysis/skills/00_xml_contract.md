# XML Output Contract (Strict)

- Return only XML requested by the prompt; do not output JSON.
- Do not include prose outside XML tags.
- If the prompt asks for `<report>`, always include both:
  - `<markdown><![CDATA[...]]></markdown>`
  - `<html><![CDATA[...]]></html>`
- If one part is hard to produce, still return non-empty placeholders in both tags.
- Keep tags stable and parsable; avoid changing tag names.
