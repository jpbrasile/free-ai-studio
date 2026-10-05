# Long-Form Video Pipeline on MiniMax H3 / FastH3: Agent Build Spec

2026-10-05 · Jean-Pierre

## Purpose and scope

The agent turns a narrative prompt into a multi-minute video with synchronized audio, unattended, using Qwen-Image 2.1 for stills and MiniMax H3 checkpoints for video in ComfyUI.

**Core principle: masters start every scene, and a rendered frame carries each scene forward.** Qwen-Image 2.1 builds the opening frame of each scene from frozen masters. Inside a scene, each clip continues from the previous clip's own ending, for at most 4 joins. Every cut to a new scene starts again from the masters, which resets drift.

**Short pieces.** If the whole piece fits in one clip, about 14 seconds, render it as a single multi-shot clip and skip chaining entirely.

**Draft fast, finish on the full model.** FastH3 is for drafts: prompts, timing, composition and cut placement. Final clips with a visible face are rendered on base H3 with a realism LoRA. FastH3 is kept for finals only on clips without people, and only if they pass the gates.

**Artifacts, not a sequence.** Every output is a content-hashed artifact that records what produced it. A change invalidates only what depends on it, so the pipeline is safe to resume and cheap to iterate.

**Status: v0.9 engineering design.** Nothing here has been run end to end. Milestone 0 below comes before any automation is built.

The pipeline runs in this order:

1. Read the operator's licence approval record; stop if it is missing.
2. Parse the prompt into a scene plan: scenes, clips per scene, shots per clip, transitions, checkpoint per clip.
3. Build the master asset library: character sheets, location plates, voice samples, room tones.
4. Generate each scene's opening frame from the masters, plus end frames where a clip must land on a set composition.
5. Draft each scene's clips on FastH3, then render candidate finals in order, chaining within the scene.
6. Measure every candidate, apply hard constraints, rank the rest, accept or escalate.
7. Assemble from the accepted-clip manifest, upscale with a video upscaler, and encode once.

## Milestone 0: validate chaining first

No agent machinery is built until one 3-clip scene has been rendered by hand and measured on the real characters, hardware and workflows. If the chaining hypothesis fails there, the higher-level design is not worth building yet.

Setup: one scene with one speaking character, 3 clips and 2 joins, rendered twice: once on FastH3, once on base H3 FL2VA with the realism LoRA. Extend the better run to 5 clips to reach 4 joins.

| Question | Measurement |
|---|---|
| Identity drift | Face-embedding similarity to the character sheet, per clip: median and spread |
| Visual drift | Brightness, contrast and face-region texture of each clip against clip 1; once with assembly-only correction, once with in-loop controls on the carried context |
| Audio degradation | High-frequency energy of each clip against clip 1, plus listening |
| Seam quality | Seam Probe and optical flow at each join, plus a blind viewing |

What the results decide: the value of `max_continuous_joins`, the default final checkpoint, whether FastH3 qualifies for any final clip, and the first gate calibrations. If identity or seams fail on base H3, stop and redesign with shorter chains, more cuts, or a different video model.

## Licensing gate

Licence clearance is external state supplied by the operator. The agent records it and checks it; it never infers clearance from geography, project purpose or revenue.

| Component | Licence | Limit to clear |
|---|---|---|
| MiniMax H3 weights, and FastH3 which derives from them | MiniMax H3 Community License | Excludes the EU, UK, South Korea and US from the permitted territory, including use of outputs. Commercial use is free under $20M yearly revenue with attribution; above that needs written authorization. ([analysis](https://contiamo.com/insights/minimax-h3-license/), [terms summary](https://www.spheron.network/blog/deploy-minimax-h3-gpu-cloud/)) |
| Qwen-Image 2.1 weights | Qwen Research License | Non-commercial unless separately licensed by Qwen. ([note](https://huggingface.co/t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy)) |

The agent reads one record and refuses to load any model whose entry is missing or not approved:

```json
{
  "license_clearance": {
    "minimax_h3": {
      "status": "APPROVED_BY_OPERATOR",
      "licence_version": "<version or date of the licence text>",
      "licence_hash": "<hash of the licence file shipped with the weights>",
      "evidence": "<path or hash of the agreement or approval>",
      "covers": ["base_weights", "derivative_weights", "outputs"],
      "approved_by": "<operator>",
      "approved_on": "<date>"
    },
    "qwen_image_2_1": { "status": "..." }
  }
}
```

Points the operator should check before approving. These are a reading aid drawn from secondary summaries of the licences, not determinations:

- The H3 territory clause concerns where the weights are run, so it applies to non-commercial work too.
- FastH3 and the Realism People LoRA are derivatives and follow the H3 licence.
- The H3 licence also restricts use of outputs outside its permitted territory.
- The Qwen Research License allows non-commercial use only.
- A move to commercial use changes the position under both licences.

Verify each point against the licence texts themselves, and against any agreement with MiniMax, before recording approval.

## Model roles and hard constraints

Each model has one job; the agent routes every clip to exactly one video checkpoint.

| Model | Job | Hard constraints |
|---|---|---|
| [Qwen-Image 2.1](https://blog.comfy.org/p/qwen-image-21-in-comfyui-open-weight) | Masters, scene opening frames, end frames | One model for generation and editing; up to 10 reference images; native 2K. Edits can shift the framing of the source picture. |
| [FastH3 8-step V2](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-fastvideo) | Drafts of every clip. Finals only for clips without visible people | Exactly 8 steps, `res_multistep` sampler, `simple` scheduler, sigma shift 10 video / 3 audio. No reference conditioning. Trades some motion and audio fidelity for speed; its own documentation recommends it for drafts and iteration. Distilled checkpoints are reported to give over-sharp, plastic-looking skin. |
| Base H3 FL2VA with the [Realism People LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA) | Final renderer for every clip with a visible face | Lands on a supplied frame precisely. MiniMax's [integration list](https://github.com/MiniMax-AI/awesome-minimax-h3-integration) notes it typically gives better raw output than Ref2VA. The blind-reviewed chaining recipe runs it at 14 steps. Several times slower than FastH3. |
| Base H3 Ref2VA with the same LoRA, or the [LightX2V Ref2VA Turbo 4-step](https://github.com/ModelTC/Minimax-H3-Turbo/wiki) checkpoint | Final clips where voice or identity must survive a cut | Up to 9 reference images, 3 reference videos and 3 audio clips ([workflow](https://comfy.org/workflows/46a303cbccf9-46a303cbccf9/)). Only nudges toward a supplied frame; reported softer than FL2VA. |
| [H3 FaceRefine](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) | Optional repair pass for small faces | Tracks each face, crops it, re-renders it with H3 and stitches it back. |
| SeedVR2 | Upscaling the assembled video | A video upscaler with temporal consistency. Never upscale video with an image model frame by frame; it flickers. |

Constraints shared by all H3 checkpoints:

- **Canvas:** 768 px short edge, 1344x768 at 16:9, dimensions rounded to multiples of 32. FastH3 does not support 1080p.
- **Minimum size:** faces distort below about 1 megapixel, so do not render under 1344x768.
- **Frame rate:** 24 fps. Other rates audibly shift voices.
- **Clip length:** frame counts on the 17k+5 grid only: 124, 141, 158, 175 ... 345. FastH3's native range is 5.167 to 14.375 seconds.
- **No negative prompt:** the templates sample at cfg 1 with a single conditioning input, so a negative prompt has no effect.
- **One conditioning family per clip:** first/last frames on an FL2VA-type checkpoint, or references on Ref2VA.
- **Versions:** ComfyUI 0.36.0 or later for FastH3 and Qwen-Image 2.1.

## Master asset library

Four kinds of master are generated once per project, frozen, and identified by content hash; every clip draws on them directly.

| Master | Content | Made with | Used as |
|---|---|---|---|
| Character sheet | One image per character with labelled panels: portrait, full front, full back | Qwen-Image 2.1 | Reference for every keyframe; image reference on Ref2VA clips |
| Location plate | One or two wide views per location, fixed materials and lighting | Qwen-Image 2.1 | Reference for every keyframe set there; image reference on Ref2VA clips |
| Voice sample | A few seconds of clean speech per speaking character | An accepted H3 render or a voice tool | Audio reference with the `reference` marker on Ref2VA clips |
| Room tone | A few seconds of ambience per location | An accepted H3 render | Audio reference with the `reference` or `weak_reference` marker on Ref2VA clips |

Rules:

- A master is never regenerated mid-project. A changed master invalidates every clip that used it.
- Reference inputs always point at masters, never at an earlier clip's output. Chaining inside a scene is the only inheritance between clips, and it is capped.
- Number or label the panels on a sheet so prompts can point at one panel, and keep printed text on the sheet to those labels.
- Store alongside each character a fixed appearance paragraph. The agent repeats it verbatim in every clip prompt where the character appears; [byte-identical text](https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow) is one of the two things reported to hold identity down a chain.

## Planning

The agent converts the narrative into a scene plan before any generation; the plan fixes scenes, clip lengths, shots, the transition entering each clip, and the checkpoint.

**Scenes.** A scene is one location at one time. It starts from a Qwen opening frame and holds at most 5 clips, which is 4 joins. A longer scene is split by a cut to a new camera setup, which restarts from the masters.

**Clip sizing.** Prefer few, long clips: target 8 to 14 seconds each. Every join discards about 1 second from the head of the next clip (22 frames, 0.92 s). Lengths must be on the 17k+5 grid.

**Dialogue budget.** A spoken line never straddles two clips. A chained clip needs about 2 quiet seconds at its head and 2 at its tail, so dialogue plus 4 seconds must fit in the clip. A 243-frame clip fits one long line; a 124-frame clip does not.

**Shots inside a clip.** H3 prompts carry several timed shots with cuts in one clip. Put same-scene cuts inside a clip whenever the shots fit; audio is then continuous by construction.

**Face size.** Plan medium and close shots for any shot where a face matters. H3 distorts faces in wide shots whatever the resolution. Where a wide shot with people is unavoidable, flag the clip for the face refinement pass.

**Transition entering each clip.** Classify every clip boundary as one of:

| Type | When | What crosses the boundary |
|---|---|---|
| `CONTINUOUS` | Next clip of the same scene and take | The previous clip's ending: 22 picture frames and 24 frames of audio from its latent |
| `CUT_SAME_LOCATION` | New camera setup in the same place | No picture. A new Qwen frame from the masters. Ambience and voice held by master audio references where needed |
| `CUT_NEW_LOCATION` | New place or time | Nothing. A new Qwen frame from the masters. Voice held by master voice reference where needed |

**Checkpoint routing.** Every clip is drafted on FastH3. For the final render the agent applies this priority table; the first matching row wins.

| Priority | Condition | Final checkpoint |
|---|---|---|
| 1 | The clip enters by a cut and needs master voice, ambience or identity references | Ref2VA with the realism LoRA |
| 2 | A face is visible | Base H3 FL2VA with the realism LoRA |
| 3 | No people, and FastH3 qualified in Milestone 0 | FastH3 |
| 4 | Anything else | Base H3 FL2VA |

A talking face that enters after a cut therefore goes to Ref2VA. Ref2VA is reported softer than FL2VA, so whether that penalty is acceptable on faces is an open item.

**Render segments.** A scene is divided into render segments. A segment is a run of chained clips on one checkpoint and one conditioning family. Inside a segment, every clip uses the highest-priority checkpoint that any of its clips needs. The checkpoint changes only at a cut, never at a continuous join. LoRA strength stays constant across the whole scene.

**Scene plan record, one per clip:**

```json
{
  "clip": 7,
  "frames": 243,
  "checkpoint": "ref2va",
  "transition_in": "CUT_SAME_LOCATION",
  "location": "kitchen_night",
  "characters": ["mara"],
  "speakers": {"S1": "mara"},
  "shots": [
    {"n": 1, "start_s": 0.0, "description": "...", "camera": "...", "dialogue": []},
    {"n": 2, "start_s": 4.5, "description": "...", "camera": "...", "dialogue": [{"speaker": "S1", "line": "..."}]}
  ],
  "start_keyframe": "kf_007_a.png",
  "end_keyframe": "kf_007_b.png",
  "references": {"pictures": ["mara_sheet", "kitchen_night_plate"], "audio": ["mara_voice", "kitchen_night_tone"]}
}
```

## Keyframe generation

Qwen-Image 2.1 makes one opening frame per scene from the masters; the rest of the scene inherits from rendered video.

**Opening frame, one per scene and one per cut:**

1. Attach the character sheet for each character in frame and the location plate. Attach nothing else.
2. Prompt with the shot's framing, pose, action and lighting, plus the character's fixed appearance paragraph.
3. Output at 1344x768 or larger with the same aspect ratio.
4. Pass the identity and set gates against the masters before use.

**End frame, only when a clip must land on a set composition:**

- Make it as a Qwen edit of that clip's start frame: change pose, state, light or one element, and hold the framing. An end frame that is an edit of the first is the [most reliable kind](https://runware.ai/docs/models/minimax-h3/guides/first-and-last-frame).
- Two unrelated frames produce a hard change partway through the clip instead of a transition.
- Keep lighting, focal length and subject angle the same in both frames, or face identity drifts between them.

**Rules for every Qwen call:**

- Edit from a master or from the scene's opening frame, never from an edit of an edit. [Artifacts accumulate](https://www.datacamp.com/tutorial/qwen-image-2-1-tutorial) when each output becomes the next input.
- Qwen 2.1 edits can shift the framing of the source. Check alignment against the source after each edit; a community [consistency LoRA](https://huggingface.co/ausboss/Qwen-Image-2.1-Consistency-LoRA) and a realign step exist for this.
- To enlarge a still without changing it, use a faithful upscaler, not a Qwen edit.

| Clip | Start frame | End frame |
|---|---|---|
| First clip of a scene, or any clip entered by a cut | Qwen opening frame | Optional |
| Later clip of a scene (`CONTINUOUS`) | None: it continues from the previous clip | Optional |

**Optional coverage pass.** For a scene that needs several camera setups, such as shot and reverse shot, one short Ref2VA generation can produce all the views from a single scene picture: static setups separated by cuts, with one frame extracted from the stable centre of each shot ([workflow](https://huggingface.co/ethanfel/H3_Cinematic_Multishot_Coverage)). Use the extracted frames as opening frames for the cut clips. Check any angle more than 90 degrees from the source, because hidden geometry is invented. Its consistency benefit is the authors' experience, not a measurement.

## Rendering rules per transition

The transition entering a clip decides its conditioning; the agent applies exactly one of these configurations.

| Setting | `CONTINUOUS` | `CUT_SAME_LOCATION` | `CUT_NEW_LOCATION` |
|---|---|---|---|
| Picture context | 22 frames | None | None |
| Audio context | 24 frames, from the previous clip's latent | None | None |
| Start keyframe | Not used | Yes | Yes |
| End keyframe | Optional | Optional | Optional |
| Picture references (Ref2VA only) | Character sheets, location plate | Character sheets, location plate | Character sheets, new location plate |
| Audio references (Ref2VA only) | Not needed | Voice sample as `reference`; room tone as `reference` | Voice sample as `reference`; new room tone as `reference` if one exists |
| Head trim after decode | 22 frames, picture and sound | None | None |

**Continuous take, exact node settings** ([H3 Motion Context](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context)):

- `context_length` 22. Valid values are 5, 22, 39 and 56; 22 is the recommended one.
- `audio_context_length` 24: one second, and on the model's audio grid.
- `encode_mode` video, `anchor_mode` head, `audio_mode` timeline.
- Feed `context_latent` from the pack's own Save Latent and Load Latent nodes. Stock latent nodes cannot hold H3's paired video and audio latent.
- Set `clip_index` explicitly on both nodes: load the clip being continued, save the clip being made. A retry then reloads the same predecessor and overwrites the reject.
- Wire `trim_frames` into the Trim node with `match_tail` on, for picture and sound.
- Keep width and height identical on both sides of the join. Context cannot cross a size change.
- An end keyframe is kept as a last-frame anchor. Any anchor that falls inside the pinned head is dropped.
- Keep step-skipping optimizers such as Spectrum disabled on these graphs.

**Simpler alternative: frame relay.** The previous clip's last frame becomes the next clip's first frame through first/last-frame mode, the duplicated frame is trimmed, and the seam audio gets a short crossfade. It needs no extra pack, but motion and sound do not carry across as exactly as with context. Use it when the Motion Context pack is unavailable.

**Why identity holds down a chain.** Every clip after the first begins from rendered pixels of the character, and the appearance and room text is repeated word for word. This held over a 40-second two-character scene with no reference images, reviewed blind, on base H3 ([Multishot pack](https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow)).

**Drift control inside a scene:**

- Use a new seed for every clip. A single seed shared across clips was measured to drift both face and voice.
- Texture and contrast ratchet upward at each join: about 1.3x per join uncorrected, about 1.02 to 1.05 with corrections.
- Level each clip's brightness and contrast to the scene's first clip, on the finished frames at assembly. This fixes what the viewer sees, not what feeds forward: the next clip still inherits the uncorrected predecessor, so assembly correction cannot stop drift that compounds through the chain. The Multishot pack reports in-loop controls that act on the carried context; Milestone 0 tests both.
- Hold the join cap set by project policy and restart from the masters at every cut.

**Cuts.** Audio references make the model match a sound rather than continue a waveform, which is the right behaviour across a cut. Give each clip only the references its own shots need. On FastH3, which has no references, a cut clip starts from its keyframe and prompt alone.

## Photorealistic people

A final clip with a visible face is rendered on base H3 with the realism LoRA, from a photographic start frame, with the face framed large. Each of the five measures below removes one known cause of plastic-looking characters.

| Cause | Measure |
|---|---|
| Distilled checkpoint: over-sharp, plastic skin | Render finals with faces on base H3, not FastH3, with all speed boosters off. |
| Base model's default skin rendering | Load the [fal Realism People LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA): one 125 MB file for text, image and reference-to-video. Start at strength 1.0 and put its trigger word `r34l1sm` at the start of the description. |
| Synthetic-looking start frame | Gate every Qwen still for realism before it becomes a keyframe. Prompt Qwen for photographic qualities: lens, natural light, visible skin texture. A waxy still passes its look to the whole scene. |
| Low resolution | Render at 1344x768 or larger. Faces distort below about 1 megapixel. |
| Small faces in frame | Plan medium and close shots. For unavoidable wide shots, run [H3 FaceRefine](https://github.com/Carasibana/ComfyUI-H3-FaceRefine) on the finished clip and lower its `blend` below 1.0 if the face comes back over-sharpened. |

Rules:

- Use the same LoRA and the same strength on every final clip of a scene. Changing it mid-scene changes the skin at a join.
- On Ref2VA clips the LoRA has a second benefit: at strength 1.0 it was [observed](https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/55) to suppress a red, painted-on skin tint that appeared without it.
- Run FaceRefine before assembly and before the video upscale, so the upscaler sees the repaired face.

Evidence limits: the LoRA's published evidence is its own 19 before-and-after pairs at the same prompt and seed, not an independent test. It follows the same MiniMax H3 Community License as the base model. Wide shots remain the weak point after all five measures.

## Prompt format

The agent emits H3's fixed prompt structure for every clip and installs MiniMax's own [prompt-writing skill](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills) rather than inventing a format. The rules below come from the [ComfyUI H3 prompt guide](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide).

**Structure.** Clips with a start or end keyframe open with the mode's fixed image-alignment line, copied from the official base guide, then one blank line. Text-only clips start directly with the fields. The body is three fields in this order:

```text
integrated_multimodal_description: [Shot 1] <overall style and opening composition, then action, camera, dialogue> [Shot 2] <...>
overall_soundscape: <ambience, action sounds, non-verbal human sounds, 1 to 4 sentences, or N/A for silence>
non_diegetic_music: <score only the audience hears, 1 to 3 sentences, or N/A>
```

**Rules the agent enforces:**

- Write in English. State the whole scene first, then break it into timed shots.
- Dialogue goes inside `<d>` tags, verbatim, in the shot where it is spoken. Speaker ID, action and delivery stay outside the tags.
- Every voice gets a stable ID, `(S1)`, `(S2)`, repeated in each shot where it speaks. IDs number speakers, not characters.
- A line that continues across a cut needs `<scenetrans>` at both connection points and a statement that the audio carries over.
- Voiceover needs the exact phrase `says in an off-screen voiceover`, then a statement that the on-screen character's lips stay closed.
- On-screen text goes in English double quotes, each string listed separately, never translated.
- Always write both audio fields explicitly. An omitted field can come back as speech nobody asked for.
- Never write a ban. Naming an unwanted element adds it to what the model reads. State what is present instead: "the sign above the door is blank", not "no text".
- For a continuous take, describe one unbroken camera move in a single shot. Do not mention cuts at all.

**Chained clips add:**

- Open holding the previous clip's exact closing arrangement, with about 2 quiet seconds of small natural motion before anyone speaks.
- Treat the first second as lost: it is replayed context and is trimmed. Dialogue starting at frame 0 loses its opening syllables.
- End settled: dialogue finished, a stable arrangement, about 2 seconds spare.
- Repeat each character's appearance and the room and lighting description word for word in every clip.
- Change the state of the world in every clip. If two clips' action lines could be swapped unnoticed, the second renders as a near-copy of the first.
- Keep the closing beat on the speaker's own body. Naming a nearby object at the end of a clip can make the model cut to it.

**Ref2VA clips add:**

- A `<Picture N>` entry per master image, describing sheets by panel. Point a shot at one panel inside the shot description.
- A relationship marker per audio reference in the retention analysis: `reference` for voice timbre and room texture, `weak_reference` for a loose atmosphere match. `fully_copy` and `partially_copy` are only for audio that must appear in the final track.
- Tie each line to a visible event, not a timecode. With two or more speakers and audio references, H3 can give a voice to the wrong speaker; if it persists, generate the line with a voice tool and supply it as that speaker's audio reference.

## Chaining, state and orchestration

The agent drives an existing production loop instead of writing its own state machine: [MiniMax H3 Context Loop](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Context-Loop) already renders one scene at a time through a reusable sampling graph with checkpoints on disk.

What the pack provides and the agent uses:

| Need | Pack feature |
|---|---|
| Scene list with prompts, seeds, timing, references | Plan node; format in `H3_CHAIN_FORMAT_GUIDE.md` in the repo |
| Catch errors before models load | Preflight: timing, media, references, compatibility, resume state |
| Per-clip continuity | Transition policy per scene: Cut carries nothing, Guide carries 22 frames |
| Audio behaviour | Audio policy: final track source, source reference, generated continuity |
| Several takes per clip | `candidate_count` above 1 generates the takes in one batch |
| Crash recovery | Atomic checkpoints, resume, partial assembly |
| Final cut | Assemble from the Loop End manifest |

Agent responsibilities on top of the pack:

1. Translate the scene plan into the pack's Plan format and submit the workflow through ComfyUI's HTTP API.
2. Map transitions: `CONTINUOUS` to Guide with generated audio continuity on; both cut types to Cut.
3. Keep its own project record per clip: prompt, seed, checkpoint, master hashes, attempt count, gate scores, accepted take.
4. Run the quality gates on each take and make the accept, retry or stop decision.
5. Request 2 or 3 candidates per clip with distinct seeds, confirm the outputs actually differ, and pass them to the acceptance logic.
6. Follow the escalation ladder on failure, with at most 3 rounds per clip; never re-roll blindly.

**Chain length.** The cap is a project policy value, `max_continuous_joins`, starting at 4. It lives in configuration so tests can move it without touching orchestration code. The starting value has two measured reasons: sound gets duller at each join, and picture gains about 13% fine texture per join even with corrections on, slight under about 4 windows and visibly over-sharpened at 7. A cut restarts both from the masters.

## Artifact graph and provenance

The pipeline is a dependency graph of content-hashed artifacts, and each artifact records exactly which upstream artifacts produced it.

```text
licence approval -> frozen masters -> plan -> keyframes -> candidate renders
  -> measurements -> acceptance -> scene manifests -> assembly -> upscale -> delivery
```

| Change | Invalidates | Leaves intact |
|---|---|---|
| A master, such as a character sheet | Keyframes and clips that used it, and everything downstream of them | Other scenes |
| A dialogue line | That clip and the later clips of its chain | Earlier clips, other scenes |
| A checkpoint, LoRA or LoRA strength | Renders that used it and their descendants | Masters, plan, keyframes |
| A gate threshold or ranking weight | Acceptance decisions | Renders and measurements |
| An assembly-level brightness correction | Assembly and later stages | Generation and gates |

**Provenance recorded with every render:**

- Hashes of the checkpoint, each LoRA with its strength, the VAEs and the text encoder.
- Hash of the workflow JSON, the ComfyUI version and the commit of every custom node.
- Prompt text, prompt-skill version, sampler, scheduler, steps, sigma settings and seed.
- Hashes of every conditioning input: keyframes, carried context, reference images and audio.
- Hashes of the masters and of the licence approval record in force.

**Candidates.** Each candidate stores its own seed, graph hash, model hashes and conditioning hashes. Two candidates count as distinct only if their seeds differ and their output hashes differ; identical outputs mean the graph is sharing deterministic state and the batch is rejected.

**Wrap, do not duplicate.** Context Loop already writes checkpoints and fingerprints for its scenes. The graph stores those identifiers as the render artifacts and adds the upstream and downstream links around them.

## Automated quality gates

Gates are split in two: hard constraints reject a take, and quality signals only rank and alert until enough human-labelled clips exist to justify thresholds.

**Hard constraints.** A take failing any of these is not eligible.

| Constraint | Method | Applies to |
|---|---|---|
| Technical validity | Frame count, resolution, duration and audio track match the plan | All clips |
| Dialogue | Speech-to-text matches the planned `<d>` lines | Clips with dialogue |
| Cut count | Scene-change detection equals the planned number of cuts | All clips; H3 can blur around a requested cut |
| Unrequested speech | Voice-activity detection finds none | Clips planned without dialogue |
| Catastrophic identity | The character is not found in most sampled frames, or the median similarity is far below the project floor | Clips with people |

**Quality signals.** Logged for every take, used for ranking and alerts.

| Signal | Method | Note |
|---|---|---|
| Identity | Face-embedding similarity to the character sheet on at least 9 frames: median, 20th percentile, and count of valid detections | The minimum is kept as a diagnostic only; profiles, motion blur and occlusion produce single bad frames |
| Set consistency | DINOv2 or SigLIP similarity to the location plate |  |
| End-frame adherence | Perceptual distance between the final frame and the end keyframe | Clips with an end keyframe |
| Picture seam | Optical flow across the join against the frames either side | `CONTINUOUS` joins only; never across a planned cut |
| Audio seam | Seam Probe: timing offset, correlation, level step, ambience floor | `CONTINUOUS` joins only |
| Audio brightness | High-frequency energy against the first clip of the chain |  |
| Voice match | Speaker-embedding similarity to the voice sample | Clips with dialogue |
| Photometric drift | Brightness and contrast against the scene's first clip |  |
| Texture drift | Fine-texture energy on matched regions, the face box and a tracked background patch, against the scene's first clip | Not the whole frame: raw high-frequency energy swings with motion, focus, grain and shot scale. Trust it only while framing correlates above 0.95 |
| Skin texture | High-frequency energy inside the face box against the scene's opening frame | A large drop means smoothed skin; a large rise means over-sharpening |
| Face size | Face box height in the first, middle and last frame | Under about 15% of frame height, route to FaceRefine |
| Still realism | Detector or aesthetic score on each Qwen keyframe | Keyframes only |

**Acceptance.**

```text
hard constraints -> eligible candidates -> normalized quality vector
  -> weighted ranking -> accept or escalate
```

Ranking weights are project configuration. The top-ranked eligible candidate is accepted if it clears a ranking floor; otherwise the clip escalates. A signal is promoted to a hard constraint only after it has been checked against human labels; 50 labelled clips per signal is a starting requirement.

**Escalation.** Deterministic, at most 3 rounds per clip.

| Failure | First step | Then | Last resort |
|---|---|---|---|
| One-off failure | New seeds |  |  |
| Repeated identity failure in a chain | Restart from the masters with a cut | Ref2VA with the character sheet as reference | Stop and return to planning |
| Face quality | Base H3 with the realism LoRA, if not already | FaceRefine | Reframe the shot closer in the plan |
| Dialogue | New seeds | Shorten the line or re-budget the clip | Supply the line as an audio reference |
| Seam | New seeds | Convert the join to a cut |  |
| Structural: wrong action, wrong cuts, wrong composition | Rewrite the prompt once | Stop and return to planning |  |

A persistent structural failure never earns more renders; it goes back to planning.

## Assembly and finishing

The final video is assembled from the manifest of accepted clips and encoded once, after upscaling.

1. Run the pack's Assemble on the completed manifest. It works on a partial manifest too, for previews.
2. Keep the per-clip generated-audio WAV files the pack saves; they are the source for any later sound mix.
3. Upscale after assembly with a video upscaler such as SeedVR2, never with an image model frame by frame. H3 renders at 768p, and the pack has a whole-chain finishing path that re-decodes every accepted checkpoint into one file-backed movie before upscaling.
4. Encode the delivery file once from the upscaled frames and the assembled audio. Have `ffmpeg` on PATH; the pack prefers it.
5. Write a delivery report: clip list, checkpoint per clip, attempts, gate scores, and any clip accepted below threshold.

## Preflight checklist

The agent verifies all of these before the first render and refuses to start if any fails.

- [ ] Licence approval record present, with status APPROVED_BY_OPERATOR for every model the plan uses
- [ ] ComfyUI 0.36.0 or later, with native Add Guide for MiniMax H3
- [ ] FastH3 8-step V2, the H3 text encoder, video VAE and audio VAE present
- [ ] A Ref2VA checkpoint present if any clip is routed to it
- [ ] Qwen-Image 2.1 weights and text encoder present
- [ ] Motion Context and Context Loop packs installed; their startup self-checks pass in the console
- [ ] ComfyUI started without `--fast fp16_accumulation`, and no custom node enables it; a user [reported](https://github.com/MiniMax-AI/MiniMax-H3/issues/84) much better reference adherence after removing it
- [ ] Spectrum, TeaCache, EasyCache and other speed boosters disabled; they were measured to distort people
- [ ] FastH3 scheduler at exactly 8 steps
- [ ] Every clip length on the 17k+5 grid, and every clip longer than its context window
- [ ] One width and height for the whole project, multiples of 32, at least 1344x768
- [ ] Every master referenced in the plan exists and matches its recorded hash
- [ ] `ffmpeg` on PATH

- [ ] Base H3 FL2VA checkpoint present for final renders
- [ ] Realism People LoRA present in `models/loras`, with one strength recorded for the project
- [ ] H3 FaceRefine installed if any clip is flagged for it

- [ ] Milestone 0 results recorded, and `max_continuous_joins` set from them
- [ ] Provenance capture working: one test render reproduces from its recorded hashes and seed
- [ ] Candidate batches produce different outputs for different seeds

## Open items to test

These are not established by the documentation; each needs a short test before the pipeline depends on it.

- [ ] **The whole chain, end to end.** No published result covers this exact combination: Qwen opening frame, chained clips, Qwen-edited end frames, video upscale. Build one 3-clip scene first and review it before scaling up.
- [ ] **FastH3 for chained clips.** The published chaining results use base H3 at 14 steps. Render the same 3-clip scene on FastH3 and on base FL2VA with the realism LoRA, and compare identity, skin, seams and audio. No published side-by-side exists; this test decides whether FastH3 is used for any final clip.
- [ ] **Qwen edit stability.** Measure how far a Qwen 2.1 edit shifts framing and face on your characters, with and without the consistency LoRA, before relying on Qwen-edited end frames.
- [ ] **Coverage pass value.** Compare coverage-pass frames with separately generated Qwen frames for one multi-angle scene; keep the pass only if it is visibly more consistent.
- [ ] **Headless accept and retry.** The pack's Review Gate is built for a person clicking in the interface. Confirm how to approve, retry and select a candidate through the API, or run with review off and gate outside the loop.
- [ ] **Audio-only context across a cut.** Carrying the previous clip's audio latent with zero picture context is not documented. If it works, it gives exact ambience continuation on FastH3 for same-location cuts. Test one cut and score it with Seam Probe.
- [ ] **Audio references on non-Ref2VA checkpoints.** Assume FastH3 and other first/last-frame checkpoints ignore them until a test shows otherwise.
- [ ] **Frame plus references in one clip.** Community hybrid checkpoints splice FL2VA and Ref2VA so a clip can open on a fixed frame and still use references. Untested here; evaluate only if cuts with voice matching prove weak.
- [ ] **Master audio length and quality.** Find the shortest voice sample and room tone that hold a match, and whether a voice-tool sample beats an H3-rendered one.
- [ ] **Gate thresholds.** Calibrate every "Calibrate" threshold, ranking weight and ranking floor against human labels. Until then every similarity and drift metric is a ranking signal, not a pass/fail gate.
- [ ] **LightX2V Ref2VA Turbo quality.** It is a 4-step v0.1 checkpoint demonstrated at 960x544; compare against base Ref2VA at the project canvas before routing clips to it.

- [ ] **Realism LoRA on FastH3.** Untested. If it works there, more final clips can stay on the fast checkpoint.
- [ ] **Realism LoRA and chaining together.** Check that the LoRA does not increase the texture ratchet at joins; measure drift on a 4-join scene with it on.
- [ ] **LoRA strength.** Compare 0.6, 0.8 and 1.0 on your characters and fix one value for the project.
- [ ] **Face-size threshold.** The 15% figure is a starting value; calibrate it against clips where the face visibly degrades.

- [ ] **Primary-source verification.** Before any statement here becomes a hard-coded rule, check it against the primary source. This applies first to the licence terms and to model capabilities taken from search summaries, which the Sources section lists.
- [ ] **Ref2VA on talking faces after a cut.** Priority 1 routing sends these to Ref2VA, which is reported softer. Compare against FL2VA without audio references and decide which loss is smaller.
- [ ] **Does photometric drift cause generational drift?** If a brighter, harder predecessor makes the next clip drift further, assembly correction cannot rescue a chain. Compare a chain with in-loop correction of the carried context against one with assembly-only correction.
- [ ] **Texture metric definition.** Fix the regions, the filter band and the normalisation for texture drift, and confirm it tracks what reviewers see.
- [ ] **Reproducibility.** Re-render one accepted clip from its provenance record on a clean install and compare.

## Sources

- [FastVideo FastH3: ComfyUI workflow examples](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-fastvideo)
- [ComfyUI MiniMax H3 prompt guide](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide)
- [H3 Motion Context, NikoDemon80](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context) and its [releases](https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context/releases)
- [MiniMax H3 Context Loop, ethanfel](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Context-Loop) and its [continuity and audio wiki page](https://github.com/ethanfel/ComfyUI-MiniMaxH3-Contex-Loop/wiki/Continuity-and-Audio)
- [MiniMax-H3 Multishot workflow, joeygambino](https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow): frame relay, drift measurements, boundary rules
- [H3 Cinematic Multishot Coverage](https://huggingface.co/ethanfel/H3_Cinematic_Multishot_Coverage)
- [ComfyUI-Continuity, roadmaus](https://github.com/roadmaus/ComfyUI-Continuity)
- [MiniMax H3 integrations list](https://github.com/MiniMax-AI/awesome-minimax-h3-integration)
- [First and last frame with MiniMax H3, Runware](https://runware.ai/docs/models/minimax-h3/guides/first-and-last-frame)
- [Qwen-Image-2.1 in ComfyUI](https://blog.comfy.org/p/qwen-image-21-in-comfyui-open-weight)
- [Qwen Image 2.1 tutorial, DataCamp](https://www.datacamp.com/tutorial/qwen-image-2-1-tutorial)
- [Qwen Image 2.1 Consistency LoRA](https://huggingface.co/ausboss/Qwen-Image-2.1-Consistency-LoRA)
- [Video upscaling in ComfyUI](https://docs.comfy.org/tutorials/utility/video-upscale) and [SeedVR2 vs FlashVSR](https://upsampler.com/blog/seedvr-vs-flashvsr-ai-video-super-resolution-2026)
- [MiniMax H3: Reference to Video workflow](https://comfy.org/workflows/46a303cbccf9-46a303cbccf9/)
- [Minimax-H3-Turbo, LightX2V checkpoints](https://github.com/ModelTC/Minimax-H3-Turbo/wiki)
- [FastH3 V2 model page, Wiro](https://wiro.ai/models/fastvideo/fast-h3-v2)
- [Ref2VA reference-fidelity issue #84](https://github.com/MiniMax-AI/MiniMax-H3/issues/84)
- [MiniMax H3 licence analysis, Contiamo](https://contiamo.com/insights/minimax-h3-license/) and [licence terms summary, Spheron](https://www.spheron.network/blog/deploy-minimax-h3-gpu-cloud/)

- [fal MiniMax H3 Realism People LoRA](https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA)
- [ComfyUI-H3-FaceRefine](https://github.com/Carasibana/ComfyUI-H3-FaceRefine)
- [Why MiniMax H3 ruins faces on wide shots, discussion](https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/30)
- [Ref2VA skin tint and realism LoRA strength, discussion](https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/55)
- [Turbo LoRA and plastic skin, discussion](https://huggingface.co/Abiray/MiniMax-H3-Turbo-Lora-Pruned-ComfyUI/discussions/2)

The realism sources above were used from search-result summaries.

Read in full: the ComfyUI docs pages, the Motion Context, Context Loop, Multishot, Coverage and Continuity pages. Search-result summaries only: the Wiro, Turbo, issue #84, integrations list, Runware, DataCamp, consistency LoRA, upscaling and licence pages.
