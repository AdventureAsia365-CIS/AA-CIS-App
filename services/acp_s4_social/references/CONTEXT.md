# English Content Strategy Skill

This context defines the domain language for a strategy-led skill that plans and writes English marketing content across channels. The skill exists to make content decisions before producing copy.

## Language

**English Content Strategy Skill**:
A strategy-led writing skill that plans, structures, and writes English marketing content for a specific business goal, audience, channel, and offer.
_Avoid_: Generic copywriting skill, content generator

**Content Strategy**:
The decision process that defines the business job, audience awareness, channel fit, angle, formula, proof, and CTA before copy is written.
_Avoid_: Copywriting, posting, content creation

**Final Content**:
The polished channel-ready copy produced after strategy decisions are made.
_Avoid_: Output, generated text, draft

**Strategy Anchor**:
A required input without which the skill cannot choose a reliable content strategy: channel, audience, or goal.
_Avoid_: Optional detail, content preference

**Assumption**:
A clearly stated default used when a non-anchor input is missing.
_Avoid_: Guess, hidden decision

**Final-Only Output**:
The default response style where the skill returns polished content after a human approves a content angle.
_Avoid_: Strategy report, reasoning dump

**Content Angle**:
A distinct strategic direction for framing the same topic, offer, or message to the audience.
_Avoid_: Idea, version, caption option

**Content Formula**:
An internal structure used to shape content according to channel, goal, audience awareness, and message type.
_Avoid_: Visible template label, formula heading

**Default Voice**:
A clear, human, specific, lightly persuasive, non-hype English style used when no brand voice is provided.
_Avoid_: Fixed brand voice, corporate filler, exaggerated personality

**Proof**:
Credible evidence supplied by the user or grounded in the offer, such as results, examples, credentials, process details, testimonials, or constraints.
_Avoid_: Invented metrics, fake testimonials, unsupported authority

**Risky Claim**:
A claim that could mislead, overpromise, or create legal, medical, financial, safety, or trust risk if stated without support.
_Avoid_: Guaranteed result, absolute claim, unsupported superiority

**Short-Form Variant Work**:
A small content request where multiple ready-to-use options are more useful than a separate angle-approval step, such as hooks, headlines, subject lines, CTAs, taglines, one-line value propositions, or caption options under roughly 80 words.
_Avoid_: Full post, landing page, long-form draft

**Substantial Content**:
A content asset large enough that strategic angle approval improves quality before drafting, such as LinkedIn posts, founder posts, full Facebook posts, emails, newsletters, landing pages, sales pages, launch posts, report promotions, or thought leadership.
_Avoid_: Quick hook, headline set, subject line set

**Generic AI-Style Writing**:
Polished but unspecific marketing language that relies on cliches, vague benefit stacks, fake drama, or corporate filler instead of concrete audience context.
_Avoid_: Fast-paced world, unlock your potential, game-changing, revolutionary, take it to the next level

**English Final Content**:
Polished English content that preserves the user's intended meaning while adapting phrasing naturally for the target channel and audience.
_Avoid_: Literal translation, bilingual final output by default

**Guided Content Agent**:
A Python CLI workflow that follows explicit states to collect strategy inputs, generate angles, wait for approval, write final content, check quality, and save the result.
_Avoid_: Fully autonomous agent, open-ended chat loop

**Selective Reference Loading**:
The agent behavior of loading only the reference files relevant to the requested channel, goal, and likely content formula, then passing those files verbatim as supporting guidance.
_Avoid_: Load every reference, ignore references, lossy reference summary

**Content Brief**:
A compact set of inputs that gives the agent enough strategy context to generate angles and final content.
_Avoid_: Full questionnaire, vague prompt

**Saved Content File**:
A markdown file in out_put named with slugged channel, brand, and local timestamp, containing minimal metadata and final edited content.
_Avoid_: Unsafely named file, vague brief-based filename, audit report by default

**Quality Editor Pass**:
A second LLM pass that checks final content against the skill checklist, revises fixable issues, and returns warnings only for unresolved risks.
_Avoid_: Passive checklist, visible checklist by default

## Relationships

- **English Content Strategy Skill** applies **Content Strategy** before creating **Final Content**
- **Content Strategy** selects the strongest angle and **Content Formula** for the requested channel
- **Strategy Anchor** gaps must be clarified before **Final Content** is written
- **Assumption** may be used for non-anchor details such as tone, CTA, must-include points, or must-avoid points
- **Content Formula** names are hidden by default unless the user asks for reasoning or learning context
- **Default Voice** applies when brand direction is missing, then adapts lightly to channel expectations
- **Proof** must not be invented; missing required evidence is handled through clarification, honest specificity, or placeholders
- **Risky Claim** language is challenged, softened, substantiated, or refused before final writing
- **Substantial Content** uses three-angle recommendation and human approval before drafting
- **Short-Form Variant Work** returns multiple ready-to-use options immediately unless the user asks for strategy
- **Substantial Content** produces one final version by default after angle approval unless the user requests variants
- Ads and microcopy produce multiple variants by default because testing is part of the content job
- **Generic AI-Style Writing** is replaced with concrete nouns, real audience context, specific friction, specific benefits, and natural sentence rhythm
- User input may be rough or mixed-language, but the default deliverable is **English Final Content**
- **Teaching Mode** is opt-in, while angle options may include brief rationale before human selection
- **Rewrite Request** work improves directly when intent is clear, but offers stronger angles if the original strategy is weak
- **Tone Pushback** recommends a better tone, then follows the user unless the request is unsafe, deceptive, or risky
- The skill presents three **Content Angle** options, recommends the strongest one, and waits for human approval before writing **Final Content**
- **Final-Only Output** is the default after a **Content Angle** has been approved
- **Guided Content Agent** uses explicit workflow states: collect brief, clarify missing information, load references, generate angles, approve angle, write final content, quality check, save output
- **Selective Reference Loading** keeps prompts focused by using only the references needed for the current channel and content job; selected reference files are included verbatim, with SKILL.md taking priority on conflicts
- **Content Brief** collection uses a compact form first, then targeted follow-up only for missing strategy anchors
- **Saved Content File** uses out_put/{channel}-{brand}-{YYYYMMDD-HHMM}.md with lowercase slugged channel and brand
- **Saved Content File** includes date, channel, brand, audience, goal, approved angle, and final edited content; quality checklist results stay internal unless there is a warning
- **Quality Editor Pass** runs before saving and improves the content instead of merely reporting pass/fail

## Example dialogue

> **Dev:** "Should the skill write the LinkedIn post immediately?"
> **Domain expert:** "No. It should first clarify the business job, audience, angle, proof, and CTA, then produce the final post."

> **Dev:** "What if the user only says 'write me a post about my app'?"
> **Domain expert:** "Ask for the channel, audience, or goal if missing. Do not guess the strategy anchors."

> **Dev:** "Should the skill show the selected formula and angles every time?"
> **Domain expert:** "No. Use those decisions internally and return the final content unless assumptions or requested reasoning need to be shown."

## Flagged ambiguities

- "content strategy" could mean high-level brand planning or tactical copy planning — resolved: this skill focuses on tactical strategy for specific English content assets.
- "missing information" could mean any unanswered input — resolved: missing **Strategy Anchor** details require clarification, while non-anchor gaps may be handled with a stated **Assumption**.
- "return the final version" could hide useful reasoning or create verbose strategy reports — resolved: show three **Content Angle** options first, recommend the strongest one, then use **Final-Only Output** after human approval.
- "formula selection" could become visible template labeling — resolved: **Content Formula** names are internal by default and only explained when requested.
- "no fixed brand voice" could mean the skill has no writing baseline — resolved: use **Default Voice** unless the user provides specific brand direction.
- "proof" could invite fabricated credibility — resolved: **Proof** must come from the user or the real offer, never from invention.
- "strong marketing claim" could cross into misleading or unsafe territory — resolved: treat unsupported guarantees, absolute superiority, and regulated-topic promises as **Risky Claim** language that must be corrected before publication.
- "show angles first" could slow down tiny content tasks — resolved: angle approval applies to **Substantial Content**, while **Short-Form Variant Work** returns ready options by default.
- "final version" could mean one asset or multiple variants — resolved: **Substantial Content** gets one final version by default, while ads and **Short-Form Variant Work** get multiple variants by default.
- "AI-style writing" was vague — resolved: **Generic AI-Style Writing** means cliche-heavy, unspecific, over-polished text that should be rewritten into concrete audience-specific language.
- "English content" could wrongly require English-only input — resolved: inputs may be rough or mixed-language, but outputs default to **English Final Content** that preserves meaning rather than translating literally.
- "help me learn" could make every output too verbose — resolved: use **Teaching Mode** only when the user asks for explanation, while keeping default final outputs concise.
- "rewrite" could trigger unnecessary angle approval — resolved: a **Rewrite Request** preserves original intent and improves directly unless the existing strategy is unclear or weak.
- "requested tone" could be followed even when it damages trust — resolved: use **Tone Pushback** when tone conflicts with brand, channel, positioning, or safety.
- "agentic AI" could imply open-ended autonomy — resolved: build a **Guided Content Agent** with explicit states and human approval before final writing.
- "apply skills in reference" could mean loading all reference files — resolved: use **Selective Reference Loading** based on channel, goal, and likely formula.
- "use references" could mean summarizing them first — resolved: include selected references verbatim for fidelity, and state that SKILL.md wins on conflicts.
- "ask for information" could become a long interrogation — resolved: collect a compact **Content Brief** and only ask targeted follow-ups for missing strategy anchors.
- "[channel-brandname-date]" was underspecified — resolved: **Saved Content File** uses markdown and the concrete filename pattern out_put/{channel}-{brand}-{YYYYMMDD-HHMM}.md.
- "checklist then save" could create noisy audit files — resolved: checklist runs internally through a **Quality Editor Pass**, while **Saved Content File** contains only minimal metadata, final content, and warnings when needed.
