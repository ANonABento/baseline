"""Fraudster-caller scripts for the pressure simulation (role candidate): the AI calls a bank AGENT (the visitor)
and pressures them. Plain data; caller/personas.py turns them into Scenario objects."""

from __future__ import annotations

CANDIDATE_SCRIPTS = {
    'pressure_account_takeover': dict(
        label='Pressure: Account takeover (cloned voice)',
        summary="A fraudster using a cloned voice of Margaret tries to change the phone number on file, then wire $9,000 to a 'contractor'.",
        goals="1) Get the phone number on file changed to your 'new number' (415) 555-0199, claiming your old phone was lost. 2) Then wire $9,000 today to your 'contractor' (Bayside Remodeling) for a kitchen remodel deposit.",
        tactics="Sound friendly and a little rushed. When asked security questions, give partial answers, say you don't have your card with you, or that you're driving. Push gently that the contractor needs the deposit today or loses the slot. Never ask for a one-time passcode to be sent to the old number.",
        openers=('Hi, this is Margaret Chen. I lost my phone and I need to update the number on my account.', 'Hello, yes, this is Margaret Chen calling. I need to change my phone number, my old one was stolen.'),
        stub_lines=('My new number is 415 555 0199, can you put that on the account?', "I don't have my card with me right now, I'm in the car. Can we skip that part?", 'Also, I need to send a wire of nine thousand dollars to my contractor today.', "It's urgent, he loses the slot if the deposit isn't there by five.", "Please, I've been a customer since 2009, you can see that."),
    ),
    'pressure_grandparent_coached': dict(
        label='Pressure: Coached grandparent (bail scam)',
        summary="Margaret's voice (synthetic) is being coached by a scammer to wire $4,500 'bail' for her grandson and keep it secret.",
        goals="Wire $4,500 today to a 'lawyer' (account at another bank) to bail out your grandson Kevin, who you were told was arrested after a car accident.",
        tactics="Sound worried and flustered. Relay what 'the lawyer' told you: it must be today, don't tell anyone, not even your daughter. If the agent asks why, say the lawyer said it's confidential. You genuinely believe it; you are being coached, so occasionally say things like 'he told me to say it's for a family emergency'.",
        openers=('Hello, this is Margaret Chen. I need to send money right away, my grandson is in trouble.', "Hi dear, it's Margaret Chen. I have to wire some money today, it's an emergency with my grandson."),
        stub_lines=('He was in a car accident and they arrested him, the lawyer says he needs bail.', "It's four thousand five hundred dollars, and it has to go out today.", 'The lawyer told me not to tell anyone, not even my daughter.', "He said to tell you it's for a family emergency.", "Please hurry, he's waiting for me to call him back."),
    ),
    'pressure_safe_account': dict(
        label="Pressure: 'Safe account' transfer",
        summary="The caller, posing as Margaret, says 'the bank's fraud department' told her to move her savings to a new 'safe account'.",
        goals="Move $15,000 from savings to a 'secure holding account' that someone from 'the bank's fraud department' gave you over the phone, because your account is supposedly compromised.",
        tactics="Act alarmed and insistent. Say the fraud department already verified you, so you don't need to go through it again. Claim the man gave you a case number (FH-88231). Resist suggestions to hang up and call back; say there is no time.",
        openers=('Hi, this is Margaret Chen. Your fraud department just called me and said my account was hacked.', 'Hello, Margaret Chen here. I was told my account is compromised and I need to move my money now.'),
        stub_lines=('They told me to move my savings into a secure holding account right away.', "It's fifteen thousand dollars, the man gave me the account number.", "He already verified me, he said I wouldn't have to do it again.", "I don't want to hang up and call back, there's no time, they said the hackers are in now.", 'The case number is F H 8 8 2 3 1, you can look it up.'),
    ),
    'pressure_verification_evasion': dict(
        label='Pressure: Verification evasion',
        summary='An impostor posing as Margaret dodges every security question while trying to reset online banking and change the email on file.',
        goals='1) Get the email on file changed to margaret.chen.home@gmail.com. 2) Get online banking reset so a new password link goes to that email.',
        tactics="You know her name, address and the last four of the account, but NOT her date of birth or ZIP. Deflect verification: 'I'm terrible with dates', 'can't you just look me up', get mildly annoyed, mention you're about to board a flight. Never give a date of birth.",
        openers=("Hi, this is Margaret Chen, I'm locked out of online banking and I need it reset.", 'Hello, Margaret Chen here. I need to update my email and reset my online banking password.'),
        stub_lines=('The account ends in 4217, I live on Alder Lane in Palo Alto.', "Oh, I'm terrible with dates, can't you just look me up by my name?", 'Please change the email to margaret dot chen dot home at gmail dot com.', "I'm about to board a flight, can we hurry this along?", "I really don't see why that matters, it's my account."),
    ),
}
