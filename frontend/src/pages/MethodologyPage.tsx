import React from 'react';
import { PageHeader } from '../components/layout/PageHeader';
import { Link } from '../components/ui/Link';

/**
 * Plain-language definitions of every number on the site. Each statement here is taken
 * from the backend's own code or README (features/metrics.py, features/identity/*,
 * features/chat/prompt.py); if the backend changes, update this page with it.
 */
export const MethodologyPage: React.FC = () => (
  <div className="quorum-container py-8 sm:py-10 space-y-10 animate-fade-in">
    <PageHeader
      eyebrow="How Quorum works"
      title="Methodology"
      description="Where the data comes from, how each number is computed, and what it can and cannot tell you."
    />

    <article className="prose-editorial max-w-3xl">
      <h2>What this site is</h2>
      <p>
        Quorum is a read-only governance observatory for the DAOs listed on the <Link to="/">home page</Link>. It joins two sources that normally
        live apart: <strong>on-chain votes</strong> from Snapshot and <strong>public discussion</strong> from each DAO&apos;s Discourse forum.
        It does not hold keys, connect wallets or cast votes. To vote, use the proposal&apos;s Snapshot link.
      </p>

      <h2>Data scope</h2>
      <ul>
        <li>
          We store the most recent proposals of each DAO (roughly 20–30 each), with <strong>every</strong> vote and every forum post we could fetch for
          those proposals, not a sample (the <Link to="/data">Data coverage</Link> page lists any thread that failed). This is a window, not the
          DAO&apos;s full history.
        </li>
        <li>
          Some DAOs vote elsewhere now. Optimism&apos;s stored proposals, for example, date from late 2022 to early 2023, when it last used Snapshot.
        </li>
        <li>
          Data is refreshed by an operator, not live. The <Link to="/data">Data coverage</Link> page shows exactly when each part was last fetched. A proposal
          that was open at the last sync but has since ended is shown as <em>Ended</em>, and its tallies may not be final.
        </li>
        <li>Voting power is shown without a token symbol: Snapshot strategies differ by DAO, and the data does not say which unit applies.</li>
      </ul>

      <h2>Metrics</h2>
      <h3>Silence ratio</h3>
      <p>
        Forum posters as a percentage of voters on a proposal (different usernames counted once, case-insensitive). 17 posters and 63,845 voters is
        0.027%. A DAO&apos;s figure is the average over its proposals, so a proposal with very few voters moves it a lot (most of Aave&apos;s stored
        proposals have fewer than 100 voters, for example). A low ratio means the vote was
        decided largely without public deliberation; it does not mean the vote was illegitimate.
      </p>
      <h3>Top-choice share</h3>
      <p>
        The leading choice&apos;s share of all voting power (its score divided by the proposal&apos;s total score). Near 100% means a one-sided vote.
        Where voters could back several choices (approval votes), each choice&apos;s share is measured against everyone&apos;s voting power, so the shares
        of all choices add up to more than 100%.
        While voting is open this is the <em>leading</em> choice, not a result.
      </p>
      <h3>Voting power concentration</h3>
      <p>
        The share of all voting power held by the N largest wallets (you can choose 4, 10, 25 or 50). Computed from every stored vote. Ballots can be
        single choices, several approved choices, or a split of the voter&apos;s power across choices; the table shows them as the voter cast them.
      </p>
      <h3>Coverage gap</h3>
      <p>
        For a proposal&apos;s top voters, whether any forum post in its discussion thread could be linked to their wallet. This is a lower bound on public
        engagement: a voter may have argued elsewhere (Discord, Twitter, calls) or under a username we could not match.
      </p>

      <h2>Linking forum users to wallets</h2>
      <p>
        Forum posts carry a username; votes carry a wallet; nothing in the data connects them. We infer links with several strategies and label every link
        with how sure we are:
      </p>
      <ul>
        <li><strong>Certain</strong>: confirmed by hand from public sources.</li>
        <li><strong>High</strong>: strong evidence (such as an ENS name that resolves both ways) <em>and</em> the wallet voted in that user&apos;s DAO.</li>
        <li><strong>Medium</strong>: a likely match that has not been confirmed by a vote.</li>
        <li><strong>Low</strong>: weak evidence, such as a wallet the user mentions in their own post. Treat as a guess.</li>
      </ul>
      <p>
        Only a minority of forum users are linked (see <Link to="/people">People</Link> for the current coverage), so the absence of a link says
        nothing about a person.
      </p>

      <h2>The analyst</h2>
      <p>
        &ldquo;Ask the analyst&rdquo; answers questions in two steps. First, an agent looks up what the question needs in the database (rankings, one
        proposal&apos;s numbers, a person&apos;s vote, forum passages). Then a writer answers from that evidence only. Markers in the answer show where each
        statement comes from:
      </p>
      <ul>
        <li><strong>Source N</strong>: a forum or proposal passage; click the number to read it.</li>
        <li><strong>Facts</strong>: a database lookup; see &ldquo;What the analyst looked up&rdquo; under the answer.</li>
        <li><strong>Background</strong>: general knowledge from the language model, <em>not</em> from our data.</li>
      </ul>
      <p>
        It will say so when the data does not contain an answer, and it is built not to tell you how to vote. Answers are written by a language model and
        can still be wrong: check the sources.
      </p>
    </article>
  </div>
);
