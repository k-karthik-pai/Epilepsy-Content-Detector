# Safety Notes

Epilepsy Guard is a safety aid for reducing exposure to potentially triggering
screen content. It is not proof that a screen is safe and does not guarantee
seizure prevention. People with epilepsy should review use of this tool with a
clinician, especially before relying on it during gaming, social media, video,
VR, or other high-risk visual activity.

The first implementation uses deterministic rules derived from public guidance:

- [W3C WCAG 2.2 Success Criterion 2.3.1 and 2.3.2](https://www.w3.org/TR/wcag/#seizures-and-physical-reactions)
  for flash limits.
- [W3C Understanding SC 2.3.1](https://www.w3.org/WAI/WCAG22/Understanding/three-flashes-or-below-threshold.html)
  for general flash and red flash thresholds.
- [ITU-R BT.1702](https://www.itu.int/rec/R-REC-BT.1702/) for broadcast-style
  photosensitive epilepsy flash guidance.
- [Ofcom flashing image and regular pattern guidance](https://www.ofcom.org.uk/siteassets/resources/documents/tv-radio-and-on-demand/broadcast-guidance/programme-guidance/broadcast-code-guidance/section-2-guidance-notes.pdf?v=322622).
- [Epilepsy Foundation photosensitivity guidance](https://go.epilepsy.com/what-is-epilepsy/seizure-triggers/photosensitivity),
  plus Epilepsy Society and Epilepsy Action patient guidance on common triggers.

The app intentionally blocks on uncertainty when `fail_closed` is enabled. This
can cause false positives, blackouts during capture problems, and interruptions
while the detector is still being tuned. That behavior is deliberate for patient
safety.

Do not test the app by displaying real strobe videos to a person with epilepsy.
Use the synthetic unit tests and offline generated frames instead.
