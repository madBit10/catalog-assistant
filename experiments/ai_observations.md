# AI listing observations (feeds the evaluation)

Problems seen in real runs, written down **before** changing the prompt. During the
evaluation (30 labelled photos), each one gets measured: how often does it happen?
Only then fix the prompt, and re-measure. (Fixing from one photo risks overfitting.)

## Log

| Date | Photo | Provider / model | Observation | Type |
|---|---|---|---|---|
| 2026-11-16 | bottle (clean) | ollama / qwen2.5vl:7b | Raw output: `is_product: false` **and** `category: "kids"`, contradicting itself. **Fixed in code** (`tidy()` forces `none`). | contradiction ✅ fixed |
| 2026-11-16 | bottle, pencil box | ollama / qwen2.5vl:7b | Correctly `is_product: false`; titles were plain names ("apple pencil case"). | ✅ correct |
| 2026-11-16 | tshirt.jpeg (stock photo, worn by a model) | ollama / qwen2.5vl:7b | category `men` ✅, colour `black` ✅, `is_product` ✅. | ✅ correct |
| 2026-11-16 | tshirt.jpeg | ollama / qwen2.5vl:7b | Title "mens motivational t-shirt": **all lowercase**, and **misses the printed text** "Mindset is EVERYTHING". | title quality |
| 2026-11-16 | tshirt.jpeg | ollama / qwen2.5vl:7b | Description adds "Comfortable fit." and the tags add "comfortable", which **can't be seen** in a photo (breaks the "never invent" rule). | invented detail |
| 2026-11-16 | tshirt.jpeg | rembg isnet | Clothing **worn by a person**: the arms come out hazy and grey; a stock **watermark** stays visible. | cleanup quality |

## Questions for the evaluation
1. How often are titles not in Title Case? (A possible code fix in `tidy()`: title-case.)
2. How often is visible printed text missed? (A possible prompt rule: "include printed text in quotes".)
3. How often are invented, unseeable claims made (comfort, material guesses, sizes)? Does Claude do it less than Ollama?
4. Does on-model clothing (worn by a person) need a different cleanup approach than flat-lay or hanger photos?

## Rules for test photos
- **Demo, README and evaluation:** only our own photos or freely licensed ones. No watermarked stock images (licence).
- Cover: flat-lay, hanger, on-model; women/men/kids/baby; thin straps/lace; printed text; plus non-clothing items.
