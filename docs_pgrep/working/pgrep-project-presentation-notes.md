# pgrep project presentation cues

Target: **4:45**. Speak naturally. Hit the points below.

## intro · 0:00–0:35

- Frank Gonzalez
- rising sophomore, MIT
- Week 2 project scope
- gaps in graduate-school exam study
- Physics GRE niche
- existing tools optimize recall
- physics requires principle selection + application
- recall is not the same as solving
- pgrep built around that gap
- brownfield project on Anki, return to this later

**Show:** opening slide, then desktop Home.

## Home demo · 0:35–1:20

- manifold
- data-driven Three.js, wrapped in Svelte
- map of Physics GRE topics
- height = Performance
- under-light = Memory
- gaps = missing evidence / low coverage

### three measurements

- Memory = “Can I recall this now?”
- Performance = “Can I apply this to a novel exam-style problem?”
- Readiness = performance + exam coverage → realistic score range
- separate instruments, separate questions
- Gauss’s Law example: remember it, still fail to recognize when it applies
- thin coverage → no fake Readiness number

**Show:** score cards, manifold labels, coverage gap. Return to deck.

## learning mechanisms · 1:20–1:50

### spaced retrieval

- FSRS scheduler
- retrievability = probability of recall right now
- difficulty + stability + elapsed time
- successful review → stronger memory → longer interval

### interleaving

- mixed Mechanics / E&M / Quantum
- exam does not label the topic
- discriminate between principles before solving

### productive failure

- commit before help
- attempt first, scaffold second
- adult / higher-education learning research
- structured instruction after the attempt
- transfer, not passive answer consumption

## tutor demo · 1:50–2:25

**Show:** tutor diagnostic → Gaussian surface / enclosed-charge problem.

- learner picked the wrong answer
- no instant full solution
- identify principle
- narrow the setup
- one scaffold at a time
- preserve learner reasoning
- in-session correctness is not the only goal

## The Experience · 2:25–3:05

### research liberty

- ask my own questions
- learning science → product decisions
- spaced retrieval, interleaving, productive failure

### independent ownership

- research → design → implementation → working demo
- complete product loop

### technical responsibility

- work carried weight
- not a disposable prototype
- understand existing Anki system
- justify each change
- transition: Brownfield engineering

## Brownfield engineering · 3:05–3:45

- pgrep inside Anki, not blank repository
- existing Rust scheduler
- FSRS retrievability model
- SQLite storage
- years of behavior users rely on
- use existing values, do not overwrite them
- preserve the system before extending it

### responsible extension

- FSRS state + scheduler = source of truth
- build new problem-generation pipeline around a corpus
- named sources / provenance
- generate candidates, do not assume they are correct
- deterministic checks + gold-set evaluation
- quality becomes testable
- add behavior without breaking existing system

## close · 3:45–4:00

- recall, application, readiness = different things
- train and measure them differently
- learning science → working product
- brownfield system → responsible extension
- thank you
- questions

**Time buffer:** use the remaining minute for clicks, pauses, or questions.
