import { redirect } from "next/navigation";

export default function Home() {
  // Default redirect — middleware sẽ handle auth
  redirect("/upload");
}
