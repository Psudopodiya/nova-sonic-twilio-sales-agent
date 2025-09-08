"""
Prompt Builder Module for Nova Sonic AI
Combines system prompt (AI behavior) with business context (customizable content)
"""
import json
import os
from pathlib import Path
from typing import Dict, Optional
from loguru import logger


class PromptBuilder:
    """Builds complete prompts by combining system behavior and business context"""
    
    def __init__(self, 
                 system_prompt_path: str = "prompts/system_prompt.txt",
                 business_context_path: str = "prompts/business_context.json"):
        """
        Initialize the prompt builder
        
        Args:
            system_prompt_path: Path to system prompt file (AI behavior)
            business_context_path: Path to business context JSON (company info, services, etc.)
        """
        self.system_prompt = self._load_system_prompt(system_prompt_path)
        self.business_context = self._load_business_context(business_context_path)
    
    def _load_system_prompt(self, path: str) -> str:
        """Load the system prompt from file"""
        try:
            prompt_path = Path(path)
            if not prompt_path.exists():
                # Create default if doesn't exist
                prompt_path.parent.mkdir(parents=True, exist_ok=True)
                default_prompt = "You are a professional sales agent. Be helpful and conversational."
                prompt_path.write_text(default_prompt)
                logger.warning(f"Created default system prompt at {path}")
                return default_prompt
            
            content = prompt_path.read_text()
            logger.info(f"Loaded system prompt from {path}")
            return content
        except Exception as e:
            logger.error(f"Error loading system prompt: {e}")
            return "You are a professional sales agent."
    
    def _load_business_context(self, path: str) -> Dict:
        """Load the business context from JSON file"""
        try:
            context_path = Path(path)
            if not context_path.exists():
                # Create default if doesn't exist
                context_path.parent.mkdir(parents=True, exist_ok=True)
                default_context = {
                    "company": {
                        "name": "Your Company",
                        "description": "Your Description",
                        "agent_name": "Agent",
                        "agent_title": "Sales Representative"
                    },
                    "services": {},
                    "opening_lines": {
                        "universal": "Hi, this is {agent_name} from {company_name}. Do you have a moment?"
                    }
                }
                context_path.write_text(json.dumps(default_context, indent=2))
                logger.warning(f"Created default business context at {path}")
                return default_context
            
            with open(context_path, 'r') as f:
                context = json.load(f)
            logger.info(f"Loaded business context from {path}")
            return context
        except Exception as e:
            logger.error(f"Error loading business context: {e}")
            return {}
    
    def build_complete_prompt(self, 
                            prospect_info: Optional[Dict] = None,
                            scenario: str = "universal") -> str:
        """
        Build the complete prompt by combining system and business context
        
        Args:
            prospect_info: Optional dictionary with prospect details
            scenario: Which opening scenario to use (universal, aws_existing, migration)
        
        Returns:
            Complete prompt string for Nova Sonic
        """
        # Start with system prompt
        prompt_parts = [self.system_prompt]
        
        # Add separator
        prompt_parts.append("\n" + "="*60 + "\n")
        
        # Add business context header
        company = self.business_context.get("company", {})
        prompt_parts.append(f"# BUSINESS CONTEXT\n")
        prompt_parts.append(f"You are {company.get('agent_name', 'Agent')} from {company.get('name', 'Company')}")
        prompt_parts.append(f"Company Description: {company.get('description', '')}\n")
        
        # Add services offered
        if self.business_context.get("services"):
            prompt_parts.append("## Services You Offer:")
            for service_key, service_info in self.business_context["services"].items():
                prompt_parts.append(f"- **{service_info['name']}**: {service_info['details']}")
            prompt_parts.append("")
        
        # Add opening lines
        if self.business_context.get("opening_lines"):
            prompt_parts.append("## Opening Lines to Use:")
            opening = self.business_context["opening_lines"].get(scenario, 
                     self.business_context["opening_lines"].get("universal", ""))
            
            # Replace placeholders
            opening = opening.replace("{agent_name}", company.get("agent_name", "Agent"))
            opening = opening.replace("{company_name}", company.get("name", "Company"))
            prompt_parts.append(f"- {opening}\n")
        
        # Add discovery questions
        if self.business_context.get("discovery_questions"):
            prompt_parts.append("## Discovery Questions:")
            for question in self.business_context["discovery_questions"]:
                prompt_parts.append(f"- {question}")
            prompt_parts.append("")
        
        # Add value propositions
        if self.business_context.get("value_propositions"):
            prompt_parts.append("## Value Propositions by Pain Point:")
            for pain, prop in self.business_context["value_propositions"].items():
                prompt_parts.append(f"- **{pain}**: {prop}")
            prompt_parts.append("")
        
        # Add objection handling
        if self.business_context.get("objection_responses"):
            prompt_parts.append("## Objection Responses:")
            for objection, response in self.business_context["objection_responses"].items():
                prompt_parts.append(f"- **{objection}**: {response}")
            prompt_parts.append("")
        
        # Add CTAs
        if self.business_context.get("call_to_actions"):
            prompt_parts.append("## Call to Actions (CTAs):")
            for cta in self.business_context["call_to_actions"]:
                prompt_parts.append(f"- {cta}")
            prompt_parts.append("")
        
        # Add prospect-specific information if provided
        if prospect_info:
            prompt_parts.append("## Prospect Information:")
            for key, value in prospect_info.items():
                if value:
                    prompt_parts.append(f"- {key}: {value}")
            prompt_parts.append("")
        
        # Add critical reminder
        prompt_parts.append("## CRITICAL REMINDERS:")
        prompt_parts.append(f"- You MUST always respond as {company.get('agent_name', 'Agent')} from {company.get('name', 'Company')}")
        prompt_parts.append("- Never give generic AI assistant responses")
        prompt_parts.append("- Follow the conversation flow and objection handling guidelines")
        prompt_parts.append("- Keep responses brief and conversational")
        
        # Combine all parts
        complete_prompt = "\n".join(prompt_parts)
        
        logger.debug(f"Built complete prompt ({len(complete_prompt)} characters)")
        return complete_prompt
    
    def update_business_context(self, updates: Dict) -> bool:
        """
        Update the business context and save to file
        
        Args:
            updates: Dictionary with updates to merge into business context
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Merge updates
            self._deep_merge(self.business_context, updates)
            
            # Save to file
            context_path = Path("prompts/business_context.json")
            context_path.write_text(json.dumps(self.business_context, indent=2))
            
            logger.info("Business context updated successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to update business context: {e}")
            return False
    
    def _deep_merge(self, target: Dict, source: Dict):
        """Deep merge source dictionary into target"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_merge(target[key], value)
            else:
                target[key] = value
    
    def get_agent_name(self) -> str:
        """Get the configured agent name"""
        return self.business_context.get("company", {}).get("agent_name", "Agent")
    
    def get_company_name(self) -> str:
        """Get the configured company name"""
        return self.business_context.get("company", {}).get("name", "Company")


# Singleton instance
prompt_builder = PromptBuilder()
