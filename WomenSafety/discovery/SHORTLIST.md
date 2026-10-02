# Shortlist: candidate demo clips (discovery only)

**Read first.** I cannot verify the content or the rights of any of these. Judgments below come ONLY from title, channel, length, view count and age as returned by the SerpApi YouTube engine; I did not open the pages, and I did not look at the thumbnails. Anything linked may depict real people being hurt (falls, assaults, robberies, and the victims are often elderly people or women). Nothing has been downloaded. A YouTube link is not permission to use a clip: see `PERMISSION_REQUEST.md`.

Candidates were found with 10 live SerpApi calls in total (6 + 4); see `*_candidates.csv` and `review.html` for the full lists (fall 24, violence 15, snatch 50). The automatic flags only catch the listed title words; most of what is below is my reading, not a flag.

## Fall

| # | Title | Channel | Length | Link | Flags | Assessment (metadata only) |
|---|---|---|---|---|---|---|
| 1 | Security Camera - Slip And Fall At Front Door From Ice | Tommy | 31 s | https://www.youtube.com/watch?v=sokd2DP457A | none | Looks like a private person's own doorstep camera: genuinely fixed, short, small channel (961 views, ~10 y old). Probably raw, but low resolution and an unusual (door-mounted) angle are likely. A private uploader is also the easiest to ask. |
| 2 | Man falls over on cctv | Matt Daley | 71 s | https://www.youtube.com/watch?v=UFf0NMHk0Ec | none | Personal channel, 90 views, plain title: likely raw CCTV. Over 60 s, so a trimmed copy would be needed. |
| 3 | Security Camera - Fall | bchris1986 | 31 s | https://www.youtube.com/watch?v=36snxi1xdQE | none | Bare title, small uploader, 19 years old: probably raw but very low quality. |
| 4 | Slip and Fall Video Surveillance | Liquid Video Technologies, Inc. | 60 s | https://www.youtube.com/watch?v=IkGOfI7h1fY | none | A security-vendor channel: real camera footage but probably selected/edited as a sales example; the vendor, not the person filmed, holds the rights. |
| 5 | CCTV Captures Guy Falling In Rain | Caters Clips | 32 s | https://www.youtube.com/watch?v=vvWpaYf1G58 | none | A viral-licensing agency: footage is probably real but re-packaged (titles/zooms) and rights are managed commercially. Least likely to give permission. |

Skipped on purpose: WooGlobe / ViralHog (agency, "hilarious" framing), the "staging a slip and fall" news items (fraud cases; edited news), "funny slip and fall" (flagged), and "CCTV-based Fall Detection" (a detection demo, probably acted, but not CCTV-originated).

## Violence

The pool is weak: of 15 candidates most are news items, robberies, a shootout, an animal attack, or a food fight (children). Only a few look like fight footage.

| # | Title | Channel | Length | Link | Flags | Assessment (metadata only) |
|---|---|---|---|---|---|---|
| 1 | Crazy fight on security camera | Gobba CGZ | 20 s | https://www.youtube.com/watch?v=dKqbUbuRxB4 | none | Small channel (128 views), plain title: plausibly raw fixed-camera fight. Unknown quality; may be cropped or screen-recorded. |
| 2 | Security Video Shows Fight Outside Pump It Up | WKRG | 88 s | https://www.youtube.com/watch?v=fCYP8G1tdQg | none | Local TV news; the footage is probably real surveillance but wrapped in a news package (and "Pump It Up" is a children's venue, so minors may be involved). Over 60 s. |
| 3 | Attack in Chicago alley caught on camera | CBS Chicago | 90 s | https://www.youtube.com/watch?v=lG6DQsPlav8 | none | News outlet: real attack on a real victim, edited with news framing. Broadcaster owns it; I would not use it. |
| 4 | Charles Oakley Fight with Knicks Security CAUGHT ON CAMERA | ABC News | 122 s | https://www.youtube.com/watch?v=PU1l6wc5S2s | none | Celebrity incident in an arena; broadcast footage with commentary, probably multi-camera. Not a clean fixed-camera clip. |
| 5 | Fight in the office, celebration gone wrong | THE FUNCYCLOPEDIANS | 99 s | https://www.youtube.com/watch?v=DhqU30dLY_s | none | 8M views and a comedy-style channel name: very likely staged or a skit. Listed only because it is "office" shaped; I would not use it. |

Not usable as a fight: "Food fight at Belmont High School" (schoolchildren), the leopard/dog attack, the Bronx gunpoint robbery and the Club Paradise shootout (violent crime, news).

## Snatch

Large pool (50), mostly Indian news items and Shorts.

| # | Title | Channel | Length | Link | Flags | Assessment (metadata only) |
|---|---|---|---|---|---|---|
| 1 | Chain Snatching from a provision store \| cctv footage!! (Malayalam title) | akri media | 39 s | https://www.youtube.com/watch?v=DMV6i8aqm3g | none | Small regional channel, "cctv footage" in the title, short: probably raw shop-camera footage. A shop-counter angle is close-up, which may suit the tracker poorly. |
| 2 | Chain Snatching from Old Lady Recorded in CCTV footage \| Caught on CCTV | CAUGHT ON CCTV | 77 s | https://www.youtube.com/watch?v=A1NPEjySaKE | none | Channel devoted to CCTV clips: likely raw or lightly captioned, a repost of someone else's footage. Over 60 s. |
| 3 | Chain Snatching Caught on Camera | PuthiyathalaimuraiTV | 52 s | https://www.youtube.com/watch?v=0vprZOJ0fhw | none | Tamil TV news channel: real footage in a news edit; broadcaster-owned. |
| 4 | Caught on CCTV : Chain snatching incident in Puducherry | DT Next | 68 s | https://www.youtube.com/watch?v=IMpbWnoCoK0 | none | Newspaper video desk: real CCTV with news framing, over 60 s. |
| 5 | Chain Snatched from Elderly Woman Inside Jaipur Home \| Robbery Caught on CCTV | NEWS9 Live | 29 s | https://www.youtube.com/watch?v=1PxvTzKcf3A | none | Jaipur (fits the demo setting) and short, but a news edit of a home robbery with an elderly victim, indoors; broadcaster-owned. |

Not recommended: "Live Robbery | Chain snatching | Cctv | India | Doge Voice over" (voice-over added), anything tagged `shorts` (vertical crops), and the flagged news/Shorts items. The Metropolitan Police "Instant karma for phone thief" (CCTV plus bodycam, 45 s) is a phone snatch from an official channel, but it mixes bodycam and is a police release.

## My single best pick per class (a suggestion for you to decide)

- **Fall: #1 "Security Camera - Slip And Fall At Front Door From Ice" (Tommy, 31 s).** Inside the 10-60 s window, a private uploader (so asking permission is realistic), and a person slipping on ice is low-drama. Risk: door-camera angle and low resolution may not suit the pose model.
- **Violence: #1 "Crazy fight on security camera" (Gobba CGZ, 20 s).** The only candidate that looks like unframed fixed-camera footage from a small uploader. A weak pick: the whole class is thin, and my own acted clip would be a safer basis.
- **Snatch: #1 "Chain Snatching from a provision store | cctv footage" (akri media, 39 s).** Raw-looking, short, small channel. The shop-counter angle may be too close for tracking.

All three are judgments from titles and numbers. Please open them yourself before deciding.
