# Brain Dump (raw, unedited)

Original voice-transcribed notes from the team, kept verbatim for reference.

---

We want to make a MVP with like a strong demo for a hackathon. So the idea is basically some sort of not like an AI detection but like an AI system to detect you know a customer or client if you're in a meeting or a call with them to basically gauge their you know their stress levels, emotions, their intent to see if they're lying about something, to see if they're interested in buying or if they're not interested and what kind of lines triggered them to react a certain way. The MVP might just be like a like a voice only model. We have access to like a 5090 so we can potentially train some sort of low level model for this. Or if we manage to finish early we can expand out to like more of a multi model with like a video and voice. One of the ideas was we can make this for potential like banks and um you know more of like a client side so to protect the low income families from getting scammed or for if it was for like a like a company to kind of screen candidates and to see if we should loan to someone you know what if they're lying about um their the income or that sort of stuff maybe integrate like a rag system or searching system into the the back end for them to basically for them like an AI to basically go and search and uh detect if they're telling the truth uh through text as well like we can have them uh look over all their look over the resume and then uh filter and research all their projects and if they're talking about something nonsensical it will flag it uh and the the recruiter might be able to you know dig deeper into it um and that's more of the recruitment side but we can also do sort of like um for businesses or banks or that involve money uh the judge we talked to one judges and they said to incorporate more of the low income and like humanity kind of how can we help for a good cause yeah for a good cause basically Another judge or a mentor basically said that we should integrate like security like what if someone wanted to uh fake their video with a filter or fake their voice with a voice changer. How do we bypass that? How do we protect companies against that?

---

## Key takeaways

- **MVP:** voice-only; stretch goal is multimodal (video + voice). RTX 5090 available for training/running a small model.
- **Signals:** stress, emotion, intent (interested vs. not), deception cues, and which lines triggered a reaction.
- **Use cases:** protecting low-income families from scams; banks/lenders checking claims like income; recruiters screening candidates.
- **RAG/search backend:** fact-check claims via text, e.g. research a resume's projects and flag nonsensical ones so a recruiter can dig deeper.
- **Judge feedback 1:** lean into low-income / humanitarian "good cause" framing.
- **Judge/mentor feedback 2:** security. Handle faked video filters and voice changers, and protect companies against them.
