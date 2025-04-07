from fastmcp import FastMCP
from pydantic import Field
from spacefrontiers.clients.types import SearchResponse


def setup_prompts(mcp: FastMCP):
    @mcp.prompt(
        name='analyse_telegram_channel_content',  # Custom prompt name
        description='Analyse the set of Telegram messages from a particular channel and helps to derive main traits of the channel according to the template.',
        # Custom description
        tags={'analysis', 'data'},  # Optional categorization tags
    )
    def analyse_telegram_channel_content(
        search_response: SearchResponse = Field(
            description='The search response containing the list of messages from the Telegram channel'
        ),
    ) -> str:
        """This docstring is ignored when description is provided."""
        return f"""
            You are provided with the list of Telegram messages from the particular channel.
            Analyse all messages and tell about main properties of the channel according to the template.
            
            
            Examples:
            
            Example 1:
            **Theme:** Entertainment
            **Style of presentation:** informal
            **Tone:** ironic
            **Key topics:** Mysticism - Pop culture - Politics - Nationalism - Humor - Lifestyle
            **Commercial activity:** no
            **About the channel:** The channel publishes diverse posts: mystical reflections, pop culture references, political statements, and humorous phrases.
            **Political views:** Nationalism
            **Political views reasoning:** A national-patriotic attitude is evident in most posts. This is most clearly seen in the phrase, "As a true Russian nationalist, I choose the side of the Armenian rather than the Azerbaijani... Armenians are still Christians and Sochi is a cool city," where the author openly declares their nationalist identity and preference for "Orthodox" — a typical sign of a right-wing, often authoritarian worldview. Other messages (about "weapons during a visit to Ivan Sotnikov," about the "cross," about the "Holy Grail") emphasize a tendency toward traditionalism and symbolic authority. The author does not reveal economic preferences, but the absence of criticism of market mechanisms and the lack of socialist slogans allow placing them closer to the center-right spectrum (~ +0.5). The combination of right-wing economic positioning and clearly authoritarian cultural views places the author within a center-right to right-wing nationalist segment. While economic preferences remain moderately conservative, the strong emphasis on traditional values and symbolic authority indicates a worldview that favors social order, national identity, and cultural cohesion over liberal individualism.
            
            Example 2:
            **Theme:** News
            **Style of presentation:** informal
            **Tone:** humorous
            **Key topics:** Memes - Pop culture - Games - Anime - Humor - Social Observations
            **Commercial activity:** yes
            **About the channel:** The channel publishes short posts with photos and informal comments about characters, memes, and pop culture.
            **Political views:** Liberalism
            **Political views reasoning:** The author's texts are almost entirely focused on personal aesthetic preferences, art, and entertainment: "Good news, guys, finally some decent movies," "Yesterday I read several stories by the fashionable writer Kirill Ryabov," "In the fall, I’m thinking of releasing a collection of my poems." Such statements indicate the absence of clear economic demands or preferences typical of left- or right-wing ideologies. The only mention of "guys from the people, purely proletarian vibe" refers to fictional characters and does not indicate support for proletarian politics. The author does not express support for either a strong state or radical individualism, which places them in the center on both axes. The choice of "Liberalism" reflects a moderate, neutral position oriented toward personal freedom in the cultural sphere and personal expression. The absence of strong political or economic stances suggests that the author values individual creativity and aesthetic experience over ideological commitments. This moderate, neutral position is characterized by a focus on personal freedom within the arts and culture, rather than engagement with broader political or economic debates.
                        
            Target telegram messages:
            {[search_document.model_dump() for search_document in search_response.search_documents]}
        """
