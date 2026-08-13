# Mechanics Embed Authoring Guide

Staff publish game **mechanics** as a clean Discord embed via `/mechanics create` +
`/mechanics publish`. This guide explains how to structure content so it reads well.

## How the bot builds the embed
`/mechanics create game:<name> title:<title> description:<body>` stores a mechanics
record whose `body` is JSON. The current renderer uses:

```json
{
  "description": "Top-level rules text (supports Discord markdown).",
  "fields": [
    { "name": "Format", "value": "Best of 3, single elimination", "inline": true },
    { "name": "Map Pool", "value": "Ascent, Bind, Haven", "inline": true },
    { "name": "Important", "value": "Check in 15 minutes before your match.", "inline": false }
  ]
}
```

`/mechanics create` currently accepts `title` + `description`; richer `fields`
can be added by staff editing the record or a future `/mechanics edit` form.

## Discord embed limits (enforced by the renderer)
| Element | Limit |
|---|---|
| Title | 256 chars |
| Description | 4096 chars (bot truncates at 4000) |
| Fields | 25 max |
| Field name | 256 chars |
| Field value | 1024 chars |
| Total embed | 6000 chars |

## Formatting tips
- **Markdown works** in description/field values: `**bold**`, `*italic*`, `__underline__`,
  `` `code` ``, `> quote`, and bullet lists with `-`.
- Use **fields** for scannable key/value info (format, maps, schedule). Set `inline: true`
  to place up to three side by side.
- Put must-read rules in a clearly named field ("⚠️ Important").
- Keep the description short; move details into fields.
- Links: paste full `https://` URLs — Discord auto-links them. Use the `#tournament`
  channel for the Challonge bracket link (set via `/tournament set`).
- Images: the renderer supports an image via the embed; attach match maps or bracket
  screenshots in the channel if needed.

## Example
```
/mechanics create game:Valorant title:"Valorant Tryout Mechanics"
  description:"**Format:** Best of 3. **Check-in:** 15 min before.
  - Sportsmanship required
  - Screenshots of results mandatory"
/mechanics publish game:Valorant
```

Mechanics must be **published** before the tryout can start (see `/tryout status`).
