# Dataset Slice Note

## Source

- Primary source used in this project: Kaggle mirror of the Enron Email Dataset
  - Link: https://www.kaggle.com/datasets/wcukierski/enron-email-dataset
- Original corpus source: Carnegie Mellon University Enron Email Dataset
  - Link: https://www.cs.cmu.edu/~enron/

## How The Slice Was Selected

- Input file: `data/emails.csv`
- Slice output: `data/laptop_slice/emails.csv`
- Goal: create a laptop-friendly subset that still preserves coherent email threads
- Date window policy: score candidate 3-6 month windows and choose the one with the strongest thread density and a message/attachment mix close to the target range
- Chosen window: `2000-11` through `2001-03` (6 months)
- Mailbox/list policy: no hard-coded mailbox restriction was applied; selection was made from the full CSV based on thread quality inside the chosen date window
- Thread policy: normalize subjects by removing prefixes such as `Re:`, `Fw:`, and `Fwd:`, then treat the normalized subject as a thread key
- Ranking policy: prefer threads with attachments and higher message counts, then stop once the slice fits the target interview-sized range

## Final Counts

- Threads: `10`
- Messages: `300`
- Attachment-bearing messages: `47`
- Approximate indexed text size: `5.83 MB`

These values come from `data/laptop_slice/summary.json`.

## Preprocessing

- Parsed raw email headers from each CSV row
- Normalized subjects to merge reply/forward variants into the same thread
- Parsed email dates and skipped malformed rows that could not be safely dated
- Increased Python CSV field size handling to support very large raw messages
- Marked a message as attachment-bearing when explicit attachment indicators were present in the raw MIME text, such as `Content-Disposition: attachment`, `filename=`, or `name=`
- Limited the final slice to a compact size suitable for laptop use and interview demos

## License / Usage Note

- The original dataset is publicly distributed through CMU and mirrored on Kaggle
- Use is subject to the source dataset terms and the hosting platform terms
- For an interview or demo project, the safest wording is: this repository contains a derived, reduced slice created from the Enron Email Dataset for local development and evaluation
- Before publishing or redistributing the full source data, review the terms on the Kaggle page and the original CMU dataset page
