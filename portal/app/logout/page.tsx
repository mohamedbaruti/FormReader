import Link from "next/link";

// Sign-in is not set up yet, so there is no session to end. When a login page
// is added, clear the session here and redirect to it.
export default function Logout() {
  return (
    <div className="page center-page">
      <div className="card narrow">
        <h1>Signed out</h1>
        <p className="lead">Sign-in is not switched on in this version, so there was no session to close.</p>
        <Link href="/" className="btn primary">Back to dashboard</Link>
      </div>
    </div>
  );
}
