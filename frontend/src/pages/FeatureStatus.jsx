import { ArrowRight, CircleHelp } from 'lucide-react';
import { Link } from 'react-router-dom';
import { PageTitle } from '../components/Feedback.jsx';
import { Insights } from './Insights.jsx';

const descriptions = {
  insights: ['Financial insights', 'Verified spending categories, cash-flow forecasts, recurring payments and monthly reports will appear here when the corresponding backend services are enabled.'],
  savings: ['Savings', 'Savings goals and authorised scheduled rules are not connected to this wallet backend yet. No funds are moved from this screen.'],
  assistant: ['AI assistant', 'The financial assistant is not connected to account-grounded tools yet. It will not guess at balances or transactions.'],
};

export function FeatureStatus({ feature }) {
  if (feature === 'insights') return <Insights />;
  const [title, detail] = descriptions[feature];
  return <><PageTitle eyebrow="FIN GUARD" title={title} detail="This section is not enabled in this installation." /><section className="feature-status-card"><span><CircleHelp size={20}/></span><div><h2>{title} is not connected yet</h2><p>{detail}</p><Link to="/overview">Return to overview <ArrowRight size={14}/></Link></div></section></>;
}
