# TriNova_Project
Our hackathon challenge focuses on exploring innovative ways to communicate medical product information so that healthcare professionals can understand its purpose, functionality, benefits, and practical applications more effectively.

# Local Clinical Knowledge Reference System

A local-first clinical knowledge reference application for retrieving, reviewing, and presenting information from a controlled collection of clinical reference documents and structured records.

The system provides document ingestion, knowledge retrieval, source tracking, structured clinical records, safety notices, and isolated encounter context in one application.

---

## Problem

Clinical reference information is often distributed across multiple documents and records, making it difficult to quickly locate relevant information and verify where it came from.

A reference system should make it easier to:

- Find relevant clinical information quickly
- Identify the source of retrieved information
- Review structured medicine and equipment records
- Keep encounter-specific information separate from general references
- Clearly indicate when information is incomplete or requires professional judgement

---

## Solution

The **Local Clinical Knowledge Reference System** provides a controlled environment where clinical reference material can be ingested, indexed, retrieved, and presented with supporting source information.

The application keeps the general reference collection separate from encounter-specific information and provides clear safety notices for situations requiring additional clinical attention.

### Core Workflow

```text
Reference Documents
        |
        v
Document Ingestion
        |
        v
Reference Storage
        |
        v
Knowledge Retrieval
        |
        v
Clinical Question
        |
        v
Relevant Information
        |
        +-- Sources / Citations
        +-- Structured Records
        +-- Safety Notices
        +-- Encounter Context
```

---

## Key Features

### Clinical Reference Collection

Supports importing controlled reference material including:

- PDF
- TXT
- Markdown
- CSV
- JSON

Source information, versions, hashes, provenance, and ingestion events are retained.

### Knowledge Retrieval

The system retrieves relevant information from the configured clinical reference collection.

Retrieved information can be traced back to its supporting source material.

### Sources and Citations

Responses can display supporting reference information such as:

- Source name
- Document information
- Page or section
- Relevant excerpt
- Source provenance

This helps users verify where reference information came from.

### Structured Clinical Records

The application can display structured records for:

- Medicines
- Clinical equipment
- Other configured clinical reference records

Records preserve stored values, units, warnings, contraindications, and provenance.

### Safety Notices

The system can display clear notices for:

- Urgent symptom patterns
- Patient-specific requests
- Requests involving calculated or adjusted doses

These notices make important limitations and safety considerations visible.

### Encounter Isolation

Encounter information is kept separate from the general clinical reference collection.

Each encounter can maintain its own:

- History
- Context
- Messages
- Encounter-specific queries

Patient context is not treated as a reference source or citation.

### Privacy-Oriented Data Separation

```text
Clinical Reference Data
        |
        +-- Documents
        +-- Sources
        +-- Records
        +-- Knowledge Index


Encounter Data
        |
        +-- Encounter
        +-- Context
        +-- History
        +-- Messages
```

Patient information must not enter the general knowledge database or reference index.

---

## System Architecture

```text
+-----------------------------------------------+
|                 React Frontend                |
|                                               |
|  Clinical Chat                                |
|  Sources / Citations                          |
|  Clinical Records                             |
|  Safety Notices                               |
|  Encounter Information                        |
+-------------------------+---------------------+
                          |
                          | HTTP API
                          v
+-----------------------------------------------+
|                FastAPI Backend                |
|                                               |
|  API Routes                                   |
|  Knowledge Management                         |
|  Clinical Workflows                           |
|  Encounter Management                         |
+----------------+------------------------------+
                 |
                 +----------------------+
                 |                      |
                 v                      v
+-------------------------+  +-------------------------+
| Clinical Knowledge     |  | Encounter Storage       |
|                         |  |                         |
| Sources                 |  | Encounters              |
| Documents               |  | Context                 |
| Records                 |  | History                 |
| Retrieved Content       |  | Messages                |
+-------------------------+  +-------------------------+
```

---

## Technology Stack

### Frontend

- React
- Vite
- JavaScript
- Tailwind CSS

### Backend

- Python
- FastAPI
- Uvicorn

### Knowledge and Storage

- Document ingestion pipeline
- Structured clinical records
- Vector-based reference indexing
- Local knowledge storage
- Separate encounter storage

### Testing

- Python `unittest`
- Backend workflow tests
- Retrieval tests
- Clinical workflow tests
- Encounter isolation tests

---

## Project Structure

```text
project/
|
+-- backend/
|   +-- api/
|   +-- config/
|   +-- encounters/
|   +-- knowledge/
|   +-- services/
|   +-- vectorstore/
|   +-- tests/
|   +-- Main.py
|   +-- requirements.txt
|
+-- rag-v3/
|   +-- src/
|   |   +-- components/
|   |   +-- context/
|   |   +-- hooks/
|   |   +-- pages/
|   |   +-- utils/
|   +-- package.json
|   +-- vite.config.js
|
+-- docs/
+-- .gitignore
+-- README.md
```

---

## Getting Started

### Prerequisites

Install:

- Python 3.x
- Node.js
- npm

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <project-directory>
```

### 2. Start the Backend

```bash
cd backend
pip install -r requirements.txt
```

Start the backend:

```bash
uvicorn Main:app --reload --port 8000
```

The backend will be available at:

```text
http://localhost:8000
```

### 3. Start the Frontend

Open another terminal:

```bash
cd rag-v3
npm install
```

Create the environment file:

```bash
cp .env.example .env
```

Set the backend URL when required:

```text
VITE_API_BASE_URL=http://localhost:8000
```

Start the frontend:

```bash
npm run dev
```

---

## Main API Areas

| Endpoint | Purpose |
|---|---|
| `/sources` | Reference source management |
| `/records` | Structured clinical records |
| `/ingestion-events` | Reference ingestion history |
| `/jobs` | Ingestion job status |
| `/query` | Reference queries |
| `/ask` | Structured reference responses |
| `/encounters` | Encounter management |
| `/encounters/{id}/messages` | Encounter history |
| `/encounters/{id}/context` | Encounter context |
| `/encounters/{id}/query` | Encounter-scoped queries |
| `/encounters/{id}/ask` | Encounter-scoped structured responses |

---

## Testing

Backend tests can be run using:

```bash
cd backend
python -B -m unittest discover -s tests -t . -v
```

The test suite covers areas including:

- Reference ingestion
- Knowledge retrieval
- Clinical workflows
- Structured records
- Safety behaviour
- Encounter isolation

---

## Safety and Privacy

This application is a **clinical reference system**, not a replacement for professional clinical judgement.

Important principles:

- Reference information should come from stored reference content.
- Unsupported information should not be presented as confirmed fact.
- Medical facts, doses, warnings, contraindications, and units should not be invented.
- Structured records should preserve their stored values and provenance.
- Patient context is separate from reference sources.
- Patient information must not enter the general knowledge store or reference index.
- Encounter operations are restricted to their associated encounter.
- Synthetic data should be used for testing and demonstrations.
- Reference material should have verified provenance and licensing before distribution.

---

## Current Project Scope

The current application focuses on:

- Clinical reference document ingestion
- Local knowledge retrieval
- Source and citation information
- Structured medicine and equipment records
- Safety notices
- Encounter-specific context and history
- Separation of reference and encounter data
- Backend API integration
- Frontend clinical reference interface

---

## Current Limitations

The project is still under development.

Areas requiring additional validation include:

- Complete frontend integration
- Browser and HTTP behaviour
- Production deployment
- Final reference collection validation
- Clinical review of safety-rule coverage
- Reference-data licensing and provenance
- End-to-end testing with the final reference collection

---

## Future Scope

Potential future improvements include:

- Improved source exploration
- More structured clinical record types
- Expanded encounter workflows
- Advanced filtering of reference material
- Better document management
- Additional validation and audit capabilities
- Production deployment improvements

---



## Disclaimer

This project is intended for **clinical reference and educational demonstration purposes**.

It does not replace qualified clinical professionals, institutional protocols, emergency services, or independent clinical judgement.

Important clinical information should always be verified against authoritative and current sources before clinical decisions are made.

