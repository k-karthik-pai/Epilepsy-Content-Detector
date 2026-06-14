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

The app logs capture uncertainty instead of blacking out so normal apps such as
browsers do not trigger a shield just because Windows capture briefly fails.
This means the shield is reserved for detected content risk, but it also means
capture failures can reduce protection until the capture path is fixed.

Do not test the app by displaying real strobe videos to a person with epilepsy.
Use the synthetic unit tests and offline generated frames instead.
