// The phone app's screens: the NIDA Portal pages in one page, without Reader Training.
// Built with build-ui.sh into android/app/src/main/python/ui/ (bundle.js + globals.css).
import { createRoot } from "react-dom/client";
import Sidebar from "@/components/Sidebar";
import Dashboard from "@/app/page";
import NewEnrolment from "@/app/enrolment/new/page";
import Enrolments from "@/app/enrolments/page";
import Settings from "@/app/settings/page";
import Logout from "@/app/logout/page";
import { useLocation } from "./stubs/router";

function App() {
  const path = useLocation().split("?")[0];
  const Page = path === "/enrolment/new" ? NewEnrolment : path === "/enrolments" ? Enrolments
    : path === "/settings" ? Settings : path === "/logout" ? Logout : path === "/" ? Dashboard : NewEnrolment;
  return (
    <>
      <div className="backdrop" aria-hidden="true"><span className="blob b1" /><span className="blob b2" /><span className="blob b3" /></div>
      <div className="shell"><Sidebar /><main className="main"><Page /></main></div>
    </>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
