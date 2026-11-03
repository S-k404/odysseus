#!/usr/bin/env python3
"""
populate_all_skills.py

Generates and installs all skills across Connectors, Hardware, Science,
Developer Tools, and Knowledge domains into Odysseus data/skills/.
Conforms exactly to Odysseus's SKILL.md specification.
"""

import os
from pathlib import Path

SKILLS_DIR = Path("/Users/shamit/Documents/Docker/Odysseus/data/skills")

SKILLS = [
    # ── CONNECTORS (Claude Desktop Suite) ──
    {
        "category": "connectors",
        "name": "blender-automation",
        "description": "Inspect 3D scenes, execute bpy automation scripts, query objects and materials, and render frames in Blender.",
        "tags": ["blender", "3d", "render", "python", "bpy", "modeling"],
        "when_to_use": "The user asks to inspect a Blender 3D file, run Blender Python automation (`bpy`), create 3D primitives, query scene objects, inspect materials, or render a viewport thumbnail.",
        "procedure": [
            "1. Verify Blender is installed via `blender_get_info`.",
            "2. To inspect scene contents, call `blender_get_scene_summary` with the `.blend` file path.",
            "3. To create objects, manipulate materials, or run transformations, use `blender_execute_code` with valid Python code utilizing `bpy`.",
            "4. To render preview images, invoke `blender_render_thumbnail` specifying resolution and destination PNG path.",
            "5. Summarize created or modified objects clearly with locations and dimensions."
        ],
        "pitfalls": [
            "Blender runs headless in background mode when executed via automation; viewport UI is not opened.",
            "Always wrap custom scripts with error handling so traceback details can be diagnosed.",
            "Ensure destination directories for renders exist before running renders."
        ],
        "verification": [
            "Return output status from Blender execution and file paths of any rendered images.",
            "Confirm object names and polygon counts if new meshes were generated."
        ]
    },
    {
        "category": "connectors",
        "name": "canva-design",
        "description": "Formulate graphic design dimensions, harmonic color palettes, typography pairings, and layout structures for Canva projects.",
        "tags": ["canva", "design", "palette", "social-media", "presentation", "layout"],
        "when_to_use": "The user asks for graphic design specs, aspect ratios, color palettes, slide layouts, social media post dimensions (Instagram, YouTube, LinkedIn), or Canva design plans.",
        "procedure": [
            "1. Call `canva_get_format_specs` to look up the exact pixel dimensions and aspect ratios for the desired medium.",
            "2. Call `canva_generate_color_palette` with the primary brand HEX code and harmony mode (complementary, triadic, analogous) to produce coordinated color codes.",
            "3. Call `canva_suggest_layout` with the design topic to obtain typography hierarchy and element placement guidelines.",
            "4. Present the complete design blueprint including HEX swatches, font pairings, and step-by-step Canva canvas setup."
        ],
        "pitfalls": [
            "Verify whether digital RGB or print CMYK resolution (300 DPI) is needed before advising dimensions.",
            "Ensure high contrast ratio between text and background colors according to WCAG standards."
        ],
        "verification": [
            "All HEX color codes are valid 6-character hex strings.",
            "Dimensions match standard modern social or print platforms."
        ]
    },
    {
        "category": "connectors",
        "name": "browser-control",
        "description": "Automate web browsing, inspect live webpages, extract DOM elements, take screenshots, and navigate using the built-in browser engine.",
        "tags": ["browser", "playwright", "web", "automation", "scrape", "screenshot"],
        "when_to_use": "The user requests inspecting a live website, filling forms, capturing page screenshots, verifying web app UI, or scraping rendered JavaScript content.",
        "procedure": [
            "1. Use `mcp__builtin_browser__browser_navigate` or native web tools to load the target URL.",
            "2. Wait for page hydration and network idle.",
            "3. Query text content, interactive elements, or take screenshots as needed.",
            "4. Provide concise summaries of on-page information with URLs cited."
        ],
        "pitfalls": [
            "Never submit sensitive passwords or authentication credentials through automation scripts.",
            "Handle cookie consent banners or modal overlays that might obscure interactive elements."
        ],
        "verification": [
            "Confirm page HTTP response status was successful (200 OK).",
            "Verify extracted data matches user requirements."
        ]
    },
    {
        "category": "connectors",
        "name": "cloudflare-developer-platform",
        "description": "Inspect Cloudflare Workers serverless deployments, DNS zone records, KV storage, and Edge network configuration.",
        "tags": ["cloudflare", "workers", "dns", "serverless", "edge", "kv"],
        "when_to_use": "The user asks about Cloudflare Workers functions, DNS records, domain routing, KV namespaces, or deployment status on Cloudflare.",
        "procedure": [
            "1. Call `cloudflare_dns_lookup` to query active DNS records (A, CNAME, TXT) for a specified domain.",
            "2. Call `cloudflare_list_workers` to list active serverless Workers scripts and their deployment timestamps.",
            "3. Report proxied status, TTL values, and routing endpoints.",
            "4. Provide guidance on `wrangler.toml` configurations or Edge optimizations."
        ],
        "pitfalls": [
            "Requires CLOUDFLARE_API_TOKEN in environment for write actions or private resource access.",
            "DNS changes have TTL propagation latency across external resolvers."
        ],
        "verification": [
            "Returned records trace directly to Cloudflare API response.",
            "No sensitive token or secret values are printed in logs."
        ]
    },
    {
        "category": "connectors",
        "name": "coursera-learning",
        "description": "Search Coursera catalog for university courses, professional certificates, specializations, and detailed syllabus outlines.",
        "tags": ["coursera", "learning", "courses", "education", "syllabus", "skills"],
        "when_to_use": "The user asks to find courses, certifications, degree programs, or syllabus details for any technical, academic, or professional subject on Coursera.",
        "procedure": [
            "1. Call `coursera_search_courses` with query keywords to discover relevant courses, degrees, or certifications.",
            "2. Inspect the top candidate course slugs.",
            "3. Call `coursera_get_course_details` with the course slug to retrieve complete description, partner institution, and language info.",
            "4. Summarize recommendations with direct links to the course pages."
        ],
        "pitfalls": [
            "Distinguish between standalone courses and multi-course Specializations or Professional Certificates.",
            "Note audit vs. paid certificate options if relevant."
        ],
        "verification": [
            "Each suggested course includes a working coursera.org URL and partner name."
        ]
    },
    {
        "category": "connectors",
        "name": "figma-design",
        "description": "Inspect Figma design files, frame hierarchies, published components, and extract design tokens (colors, typography).",
        "tags": ["figma", "design", "tokens", "components", "ui-ux", "styles"],
        "when_to_use": "The user asks to inspect a Figma file, extract design tokens, look up component libraries, or translate Figma layouts into CSS/React code.",
        "procedure": [
            "1. Extract file key from the Figma URL if a link was provided.",
            "2. Call `figma_get_file_info` to retrieve document hierarchy, pages, and frame names.",
            "3. Call `figma_extract_design_tokens` to extract color variables and typography styles.",
            "4. Translate tokens into CSS custom properties (`--color-primary`, etc.) or Tailwind config."
        ],
        "pitfalls": [
            "Requires FIGMA_ACCESS_TOKEN for live private files; explain how to obtain one if missing.",
            "Large design files can contain thousands of layers; limit depth when inspecting."
        ],
        "verification": [
            "Design tokens include standard RGB/HEX and font weights.",
            "File metadata matches the intended project."
        ]
    },
    {
        "category": "connectors",
        "name": "github-integration",
        "description": "Search repositories, read remote file contents, inspect open issues and pull requests, and review commits via GitHub API.",
        "tags": ["github", "git", "repositories", "code-search", "issues", "pull-requests"],
        "when_to_use": "The user asks to search GitHub repositories, read files from a public or private repo, or inspect open issues/PRs on GitHub.",
        "procedure": [
            "1. Use `github_search_repos` to locate repositories by name, topic, or language qualifier.",
            "2. Use `github_get_file_contents` to fetch specific source files or READMEs without cloning.",
            "3. Use `github_list_issues` to review bug reports or active discussions.",
            "4. Cite exact repository URLs and branch references in the response."
        ],
        "pitfalls": [
            "Unauthenticated GitHub API has a 60 req/hr rate limit; recommend GITHUB_TOKEN for heavy usage.",
            "Check default branch name (main vs master) when fetching raw file contents."
        ],
        "verification": [
            "Links trace to real github.com paths.",
            "File text accurately reflects remote repository contents."
        ]
    },
    {
        "category": "connectors",
        "name": "gmail-assistant",
        "description": "Search emails, list inboxes, draft replies, and organize messages using Odysseus Email / Gmail integration.",
        "tags": ["gmail", "email", "inbox", "imap", "smtp", "messages"],
        "when_to_use": "The user asks to search emails, read recent messages, draft an email reply, or summarize conversations from their inbox.",
        "procedure": [
            "1. Use `mcp__email__list_email_accounts` or `list_email_accounts` to verify connected inboxes.",
            "2. Use `mcp__email__list_emails` with search query or sender filter to retrieve message headers.",
            "3. Use `mcp__email__read_email` to inspect full message body and attachments.",
            "4. To send or reply, always draft the message first and verify user consent before dispatch."
        ],
        "pitfalls": [
            "Never send an email automatically without showing the recipient, subject, and draft text to the user.",
            "Respect privacy: do not log or store private credentials."
        ],
        "verification": [
            "Confirmed user intent before sending any outgoing email.",
            "Message IDs and timestamps match real inbox data."
        ]
    },
    {
        "category": "connectors",
        "name": "google-drive-workspace",
        "description": "Search Google Drive files, read Google Docs/Sheets content, and inspect folder hierarchies in Google Workspace.",
        "tags": ["google-drive", "gdrive", "docs", "sheets", "workspace", "cloud-storage"],
        "when_to_use": "The user asks to find files in Google Drive, read a Google Doc, inspect Google Sheets data, or check shared documents.",
        "procedure": [
            "1. Call `gdrive_search_files` with keywords to find matching documents, spreadsheets, or folders.",
            "2. Call `gdrive_read_file_metadata` to retrieve file owner, last modified time, and web view link.",
            "3. If reading document text, extract clean paragraphs or markdown table representations.",
            "4. Provide direct clickable Drive links to the found files."
        ],
        "pitfalls": [
            "Requires GOOGLE_DRIVE_TOKEN or Workspace OAuth configuration.",
            "Google Sheets with complex formulas should be formatted as clean tabular data."
        ],
        "verification": [
            "File IDs match real Google Drive items.",
            "Permissions are verified before attempting deep reads."
        ]
    },
    {
        "category": "connectors",
        "name": "pubmed-literature",
        "description": "Query NCBI PubMed for biomedical research, clinical trials, scientific publications, and full abstracts using PMIDs.",
        "tags": ["pubmed", "ncbi", "biomedical", "medicine", "clinical", "research", "pmid"],
        "when_to_use": "The user asks to search medical literature, clinical research, genetics/pharmacology papers, PubMed abstracts, or verify claims using peer-reviewed publications.",
        "procedure": [
            "1. Call `pubmed_search` with keywords, disease name, gene symbol, or drug compound to get relevant PMIDs.",
            "2. Review publication titles, journals, and dates.",
            "3. Call `pubmed_get_abstract` with specific PMIDs to fetch full abstract text and author affiliations.",
            "4. Synthesize findings citing PMID, journal name, year, and direct pubmed.ncbi.nlm.nih.gov links."
        ],
        "pitfalls": [
            "Always cite the exact PMID so the user can verify clinical findings.",
            "Distinguish between in vitro, animal model, and human clinical trial evidence."
        ],
        "verification": [
            "Every cited claim includes its corresponding PMID link.",
            "Abstract text accurately mirrors PubMed record."
        ]
    },

    # ── HARDWARE & ELECTRONICS (KiCad & Lab Suite) ──
    {
        "category": "hardware",
        "name": "kicad-eda",
        "description": "Analyze KiCad PCB schematics, netlists, component footprints, PCB layers, and Design Rule Checks (DRC).",
        "tags": ["kicad", "pcb", "schematic", "eda", "hardware", "electronics", "circuit"],
        "when_to_use": "The user asks to inspect KiCad schematics (`.kicad_sch`), PCB layouts (`.kicad_pcb`), netlists, bill of materials, or check design rules.",
        "procedure": [
            "1. Call `kicad_eda_server` tools to parse schematic files in the workspace.",
            "2. List components, reference designators, and pin connections.",
            "3. Validate decoupling capacitors on power rails (VCC/VDD to GND).",
            "4. Review track widths, clearance rules, and differential pair routing.",
            "5. Generate a structured report with design warnings and recommendations."
        ],
        "pitfalls": [
            "Check for floating inputs on digital ICs and missing pull-up/pull-down resistors on I2C/SPI lines.",
            "Ensure crystal oscillator traces have short return paths and guard rings."
        ],
        "verification": [
            "All components have assigned footprints.",
            "Netlist connects all active pins without dangling nets."
        ]
    },
    {
        "category": "hardware",
        "name": "emc-compliance",
        "description": "EMC/EMI pre-compliance risk analysis for PCB designs: ground planes, decoupling, return paths, differential skew, and edge radiation.",
        "tags": ["emc", "emi", "compliance", "pcb", "fcc", "noise", "grounding"],
        "when_to_use": "The user asks about EMC/EMI risks, passing FCC/CE certification, high-speed signal integrity, ground loops, or radiated emissions.",
        "procedure": [
            "1. Inspect PCB stackup: ensure solid unbroken reference ground plane under high-speed traces.",
            "2. Check switching power supplies (buck/boost converters): loop area between inductor, diode, and input capacitor must be minimal.",
            "3. Verify decoupling capacitors: place smallest values (0.1uF / 10nF) closest to IC power pins.",
            "4. Check board edge clearance (20H rule) to avoid edge radiation.",
            "5. Produce a categorized risk report with severity rankings (High, Medium, Low)."
        ],
        "pitfalls": [
            "Avoid routing high-speed signal traces across splits or voids in the ground plane.",
            "Ensure clock oscillators have series damping resistors near the driver pin."
        ],
        "verification": [
            "No high-speed traces cross plane splits.",
            "Decoupling loop inductances are minimized."
        ]
    },
    {
        "category": "hardware",
        "name": "spice-simulation",
        "description": "Run analog circuit simulations (ngspice/LTspice) for RC/LC filters, voltage dividers, opamps, and oscillators.",
        "tags": ["spice", "simulation", "analog", "circuits", "filter", "opamp", "frequency"],
        "when_to_use": "The user asks to simulate an analog circuit, verify filter cutoff frequencies, check amplifier gain/bandwidth, or run transient analysis.",
        "procedure": [
            "1. Construct standard SPICE netlist syntax with components, sources, and models.",
            "2. Define analysis directives (.ac for frequency response, .tran for time domain, .op for DC bias).",
            "3. Execute simulation and extract peak voltages, cutoff frequencies (-3dB point), or settling times.",
            "4. Plot or tabularize results comparing design target vs simulation output."
        ],
        "pitfalls": [
            "Ensure ground node is explicitly labelled as node 0.",
            "Check component units: 'm' is milli, 'meg' is mega in SPICE."
        ],
        "verification": [
            "Simulation converges without singular matrix errors.",
            "Calculated cutoff frequency matches theoretical equations."
        ]
    },
    {
        "category": "hardware",
        "name": "datasheet-extraction",
        "description": "Extract structured pinouts, electrical limits, voltage thresholds, and peripheral features from component datasheet PDFs.",
        "tags": ["datasheet", "pinout", "voltage", "ic", "specs", "hardware"],
        "when_to_use": "The user asks for electrical specifications, pin functions, recommended operating conditions, or thermal limits for a specific electronic component MPN.",
        "procedure": [
            "1. Search local datasheets folder or query manufacturer documentation by MPN.",
            "2. Extract Absolute Maximum Ratings (supply voltage, pin input voltage, junction temperature).",
            "3. Extract Recommended Operating Conditions and logic thresholds (V_IH, V_IL).",
            "4. Map pin numbers to signal names and alternate functions.",
            "5. Present extracted data in a clean reference table."
        ],
        "pitfalls": [
            "Distinguish between Absolute Maximum Ratings and Recommended Operating Conditions.",
            "Confirm package variant (QFN, TSSOP, SOIC) as pinouts often differ by package."
        ],
        "verification": [
            "Pin numbers match the exact package suffix of the MPN."
        ]
    },
    {
        "category": "hardware",
        "name": "bom-sourcing",
        "description": "Generate, cross-reference, and audit Bill of Materials (BOM) across DigiKey, Mouser, and LCSC for pricing and availability.",
        "tags": ["bom", "sourcing", "pricing", "inventory", "digikey", "mouser", "lcsc"],
        "when_to_use": "The user asks to create a BOM, check part availability, find cheaper or second-source alternatives, or prepare for manufacturing.",
        "procedure": [
            "1. Aggregate components from schematic: reference designators, MPN, value, footprint, tolerance, voltage rating.",
            "2. Check stock levels and volume price breaks across distributors.",
            "3. Identify obsolete or single-source components and propose drop-in replacements.",
            "4. Format final BOM in standard CSV/Excel format with distributor part numbers."
        ],
        "pitfalls": [
            "Verify lifecycle status (Active vs Not Recommended for New Designs / EOL).",
            "Ensure passive component package sizes (e.g. 0603, 0805) match available footprint pads."
        ],
        "verification": [
            "Every entry has non-zero stock or an active replacement.",
            "Total estimated board BOM cost is computed."
        ]
    },

    # ── SCIENCE & LIFE SCIENCES ──
    {
        "category": "science",
        "name": "alphafold-structure",
        "description": "Retrieve and inspect AlphaFold 3D protein structures, per-residue pLDDT confidence scores, and domain boundaries by UniProt ID.",
        "tags": ["alphafold", "protein", "structure", "uniprot", "plddt", "bioinformatics"],
        "when_to_use": "The user provides a UniProt Accession ID and asks about structural prediction, confidence scores (pLDDT), disorder regions, or 3D coordinates.",
        "procedure": [
            "1. Validate the UniProt Accession ID (e.g. P04637 for TP53).",
            "2. Query AlphaFold DB API (`https://alphafold.ebi.ac.uk/api/prediction/{uniprot_id}`).",
            "3. Download `.cif` or `.pdb` coordinates and fetch the predicted alignment error (PAE) matrix.",
            "4. Analyze pLDDT bands: >90 (very high), 70-90 (confident), 50-70 (low), <50 (very low / disordered).",
            "5. Summarize well-folded domains vs flexible loops."
        ],
        "pitfalls": [
            "Do not interpret low pLDDT regions (<50) as structured: these are often intrinsically disordered.",
            "AlphaFold DB predictions are monomeric unless AlphaFold-Multimer complex predictions are queried."
        ],
        "verification": [
            "UniProt ID verified in UniProtKB.",
            "Mean pLDDT score calculated across the sequence."
        ]
    },
    {
        "category": "science",
        "name": "chembl-bioactivity",
        "description": "Query ChEMBL database for bioactive small molecules, drug targets, IC50/Ki/Kd values, and chemical structures.",
        "tags": ["chembl", "bioactivity", "pharmacology", "drug-discovery", "ic50", "compounds"],
        "when_to_use": "The user asks about drug molecules, target affinities, binding assays, mechanism of action, or bioactivity thresholds in ChEMBL.",
        "procedure": [
            "1. Query ChEMBL REST API (`https://www.ebi.ac.uk/chembl/api/data`).",
            "2. Resolve target protein to ChEMBL Target ID (e.g. CHEMBL203 for EGFR).",
            "3. Filter bioactivity data by standard type (IC50, Ki, Kd) and standard units (nM).",
            "4. Rank compounds by potency (lowest nanomolar values indicate highest potency).",
            "5. Present compound SMILES, molecular weight, and target references."
        ],
        "pitfalls": [
            "Ensure standard units are converted consistently (uM vs nM).",
            "Differentiate between biochemical assays and cell-based functional assays."
        ],
        "verification": [
            "Assay ChEMBL ID matches target organism (e.g. Homo sapiens).",
            "Data points cite published literature references."
        ]
    },
    {
        "category": "science",
        "name": "uniprot-protein",
        "description": "Retrieve comprehensive protein metadata, sequence, functional annotations, isoforms, and gene ontology from UniProtKB.",
        "tags": ["uniprot", "protein", "sequence", "fasta", "enzymes", "genetics"],
        "when_to_use": "The user asks about a protein's amino acid sequence, catalytic residues, post-translational modifications, subcellular localization, or UniProt identifiers.",
        "procedure": [
            "1. Search UniProtKB (`https://rest.uniprot.org/uniprotkb/search?query=...`).",
            "2. Retrieve primary accession, entry name, gene names, and organism.",
            "3. Extract functional descriptions, catalytic active sites, binding domains, and transmembrane regions.",
            "4. Fetch FASTA sequence if requested.",
            "5. Provide links to UniProtKB entry."
        ],
        "pitfalls": [
            "Verify species when querying (human vs mouse vs yeast).",
            "Distinguish between reviewed Swiss-Prot entries and unreviewed TrEMBL entries."
        ],
        "verification": [
            "Accession format verified (6 or 10 characters alphanumeric).",
            "Sequence length matches published isoform 1."
        ]
    },
    {
        "category": "science",
        "name": "clinvar-pathogenicity",
        "description": "Inspect human genetic variant clinical significance, pathogenicity classifications (Pathogenic, Benign, VUS), and evidence in ClinVar.",
        "tags": ["clinvar", "genetics", "pathogenicity", "variants", "clinical", "vus"],
        "when_to_use": "The user asks whether a human mutation or variant is pathogenic, benign, or variant of uncertain significance (VUS) in ClinVar.",
        "procedure": [
            "1. Query NCBI ClinVar by rsID, HGVS nomenclature, or genomic coordinate.",
            "2. Retrieve clinical significance classification and review status (gold stars rating).",
            "3. Extract associated diseases and conditions.",
            "4. Summarize submitted evidence, ACMG criteria guidelines, and conflicting classifications if present."
        ],
        "pitfalls": [
            "Variants may have conflicting classifications from different submitters; report consensus.",
            "Always state that ClinVar interpretations are for research information and not clinical medical advice."
        ],
        "verification": [
            "Variation ID and review star rating are cited.",
            "Condition names match OMIM / MedGen terminology."
        ]
    },

    # ── DEVELOPER TOOLS & WORKSPACE ──
    {
        "category": "developer",
        "name": "sqlite-database",
        "description": "Inspect SQLite databases, examine table schemas, run analytical SQL queries, and inspect relations using sqlite_explorer.",
        "tags": ["sqlite", "sql", "database", "query", "schema", "tables"],
        "when_to_use": "The user asks to inspect a `.db` or `.sqlite` file, examine table columns, query records, check indices, or diagnose database performance.",
        "procedure": [
            "1. Call `mcp__sqlite_explorer__sqlite_list_tables` with database path to list existing tables and row counts.",
            "2. Call `mcp__sqlite_explorer__sqlite_describe_table` to get table column names, types, primary keys, and foreign keys.",
            "3. Execute read-only SQL queries via `mcp__sqlite_explorer__sqlite_query` to sample data or run aggregate computations.",
            "4. Format result sets in clean Markdown tables."
        ],
        "pitfalls": [
            "Use read-only queries (SELECT) unless user explicitly requests data mutation.",
            "Use LIMIT clauses on queries against large production tables."
        ],
        "verification": [
            "Query results returned cleanly without database locking errors."
        ]
    },
    {
        "category": "developer",
        "name": "arxiv-research",
        "description": "Search arXiv academic preprints, inspect abstracts, find author publications, and download direct research PDFs.",
        "tags": ["arxiv", "research", "academic", "papers", "ai", "preprints"],
        "when_to_use": "The user asks to search for research papers in computer science, machine learning, physics, math, or engineering on arXiv.",
        "procedure": [
            "1. Call `mcp__arxiv_research__search_arxiv_papers` with keyword query and result limit.",
            "2. Inspect paper titles, authors, categories, and abstracts.",
            "3. For specific papers of interest, call `mcp__arxiv_research__get_arxiv_paper` with the clean arXiv ID (e.g. '2310.06825').",
            "4. Provide synthesized summaries with direct links to the paper and PDF."
        ],
        "pitfalls": [
            "Clean 'arxiv:' or 'abs/' prefixes before passing arXiv ID to `get_arxiv_paper`.",
            "Ensure queries are specific enough to avoid thousands of generic hits."
        ],
        "verification": [
            "Direct links to arxiv.org/abs/ and arxiv.org/pdf/ are included."
        ]
    },
    {
        "category": "developer",
        "name": "obsidian-vault",
        "description": "Search, read, create, and link notes inside an Obsidian markdown knowledge vault.",
        "tags": ["obsidian", "notes", "vault", "markdown", "knowledge-graph", "zettelkasten"],
        "when_to_use": "The user asks to search their Obsidian vault, read existing notes, append daily notes, or create linked markdown files in Obsidian.",
        "procedure": [
            "1. Call `mcp__obsidian__manage_obsidian` to search notes by title, tag, or content keyword.",
            "2. Read target note to review current structure.",
            "3. When creating or updating notes, preserve wikilinks (`[[Note Name]]`) and YAML frontmatter.",
            "4. Confirm note location relative to the active Obsidian vault root."
        ],
        "pitfalls": [
            "Do not overwrite existing notes without reading them first.",
            "Respect the user's Obsidian folder organization and attachment folders."
        ],
        "verification": [
            "Note appears in search results and contains valid YAML frontmatter."
        ]
    },
]

def install_skills():
    count = 0
    for s in SKILLS:
        cat = s["category"]
        name = s["name"]
        target_dir = SKILLS_DIR / cat / name
        target_dir.mkdir(parents=True, exist_ok=True)
        file_path = target_dir / "SKILL.md"

        tags_str = ", ".join(s["tags"])
        proc_str = "\n".join(s["procedure"])
        pit_str = "\n".join(f"- {p}" if not p.startswith("-") else p for p in s["pitfalls"])
        ver_str = "\n".join(f"- {v}" if not v.startswith("-") else v for v in s["verification"])

        content = f"""---
name: {name}
description: "{s['description']}"
version: 1.0.0
category: {cat}
tags: [{tags_str}]
status: published
confidence: 0.95
source: built-in
owner: admin
---

## When to Use

{s['when_to_use']}

## Procedure

{proc_str}

## Pitfalls

{pit_str}

## Verification

{ver_str}
"""
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        count += 1
        print(f"✔ Installed skill: {cat}/{name}")

    print(f"\nSuccessfully installed {count} skills into {SKILLS_DIR}!")

if __name__ == "__main__":
    install_skills()

