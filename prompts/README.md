# Prompt System Documentation

## Overview
The Nova Sonic AI uses a two-tier prompt system that separates:
1. **System Prompt** - How the AI behaves (tone, conversation style, rules)
2. **Business Context** - What the AI talks about (company, services, scripts)

This separation allows you to easily customize the business content without touching the core AI behavior.

## File Structure
```
prompts/
├── system_prompt.txt       # AI behavior configuration
├── business_context.json   # Business/sales information
└── README.md               # This file
```

## System Prompt (`system_prompt.txt`)
This file controls HOW the AI speaks and behaves:
- Voice characteristics (warm, confident, natural)
- Turn-taking rules (brief responses, one question at a time)
- Discovery approach (listen first, understand needs)
- Objection handling style (respectful, never pushy)
- Compliance boundaries (no PII, honest about capabilities)

**When to edit:** Only when you want to change the AI's personality or conversation style.

## Business Context (`business_context.json`)
This JSON file contains WHAT the AI talks about:

### Structure:
```json
{
  "company": {
    "name": "Your Company Name",
    "description": "Your company description",
    "agent_name": "Alex",
    "agent_title": "Sales Consultant"
  },
  
  "services": {
    "service_key": {
      "name": "Service Name",
      "details": "Detailed description of the service"
    }
  },
  
  "opening_lines": {
    "universal": "Default opening line",
    "aws_existing": "For existing AWS customers",
    "migration": "For migration prospects"
  },
  
  "discovery_questions": [
    "Your discovery questions here"
  ],
  
  "value_propositions": {
    "pain_point": "How you solve it"
  },
  
  "objection_responses": {
    "objection_type": "Your response"
  },
  
  "call_to_actions": [
    "List of CTAs"
  ]
}
```

## How to Customize for Your Business

### 1. Edit Company Information
Update the `company` section with your details:
```json
"company": {
  "name": "YourCompany",
  "description": "Leading provider of...",
  "agent_name": "Sarah",
  "agent_title": "Account Executive"
}
```

### 2. Define Your Services
Add your services/products in the `services` section:
```json
"services": {
  "consulting": {
    "name": "Technical Consulting",
    "details": "We provide expert consulting for..."
  },
  "support": {
    "name": "24/7 Support",
    "details": "Round-the-clock technical support..."
  }
}
```

### 3. Customize Opening Lines
Create different openers for different scenarios:
```json
"opening_lines": {
  "universal": "Hi, this is {agent_name} from {company_name}. We help businesses [your value prop]. Do you have 30 seconds?",
  "existing_customer": "Hi {agent_name} from {company_name}. I see you're already using our platform. Got a moment to discuss new features?",
  "cold_call": "Hi, {agent_name} here from {company_name}. Quick call about [specific pain point]. Is now a bad time?"
}
```

### 4. Add Discovery Questions
Questions to understand prospect needs:
```json
"discovery_questions": [
  "What's your current setup for [relevant area]?",
  "What's the biggest challenge you're facing with [pain point]?",
  "Who's involved in decisions about [your solution area]?",
  "What's your timeline for making changes?"
]
```

### 5. Define Value Propositions
Map pain points to your solutions:
```json
"value_propositions": {
  "cost": "We typically reduce costs by 30% through...",
  "efficiency": "Our automation saves 10 hours per week...",
  "compliance": "We ensure full compliance with..."
}
```

### 6. Handle Common Objections
Prepare responses for typical objections:
```json
"objection_responses": {
  "not_interested": "I understand. May I send you a one-page overview for future reference?",
  "no_budget": "Many clients start with our free assessment to identify savings opportunities.",
  "happy_with_current": "That's great! We often complement existing solutions. Worth a 5-minute comparison?"
}
```

## Using Dynamic Prospect Information

When making a call, you can pass prospect-specific information:

```bash
curl -X POST http://localhost:7860/make-call \
  -H "Content-Type: application/json" \
  -d '{
    "to": "+1234567890",
    "voice_id": "mathew",
    "scenario": "aws_existing",
    "prospect_info": {
      "prospect_name": "John Smith",
      "prospect_company": "ABC Corp",
      "industry": "Healthcare",
      "known_stack": "AWS",
      "primary_pain": "cost optimization"
    }
  }'
```

The AI will use this information to personalize the conversation.

## Testing Your Prompts

### 1. Quick Test
After editing, make a test call to see how the AI performs:
```bash
python validate_setup.py  # Check setup
python server.py          # Start server
# Make a test call
```

### 2. Iterate
- Listen to how the AI sounds
- Note what works and what doesn't
- Adjust the prompts accordingly
- Test again

## Best Practices

### DO:
- Keep opening lines under 6 seconds when spoken
- Use placeholders like `{agent_name}` and `{company_name}`
- Keep value propositions concise and specific
- Test with real phone calls, not just reading

### DON'T:
- Make the AI claim to be human
- Promise specific outcomes or timelines
- Include sensitive information in prompts
- Make scripts too long or complex

## Examples for Different Industries

### SaaS Company
```json
"opening_lines": {
  "universal": "Hi, {agent_name} from {company_name}. We help teams ship code 50% faster. Got 30 seconds?"
}
```

### Consulting Firm
```json
"opening_lines": {
  "universal": "Hi, {agent_name} from {company_name}. We're helping companies in your industry reduce cloud costs by 40%. Quick question - are you using AWS or Azure?"
}
```

### Healthcare Tech
```json
"opening_lines": {
  "universal": "Hi, {agent_name} from {company_name}. We help healthcare providers stay HIPAA compliant while modernizing. Do you have a moment?"
}
```

## Troubleshooting

### AI sounds too robotic
- Simplify the language in business_context.json
- Use shorter sentences
- Add conversational phrases

### AI doesn't mention company name
- Check that `{agent_name}` and `{company_name}` placeholders are used
- Verify company section is properly filled

### AI gives generic responses
- Make sure business_context.json has specific content
- Add more detailed service descriptions
- Include specific value propositions

## Need Help?
- Check logs for prompt building: `grep "Built prompt" logs/*.log`
- Test prompt separately: `python -c "from prompt_builder import prompt_builder; print(prompt_builder.build_complete_prompt())"`
- Validate JSON: `python -m json.tool prompts/business_context.json`
