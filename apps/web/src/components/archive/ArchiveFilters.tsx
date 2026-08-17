import { SlidersHorizontal } from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";

import { Dialog, DialogContent, DialogTrigger } from "../ui/Dialog";
import { Button } from "../ui/Button";
import { Input } from "../ui/Input";
import type { DocumentListFilters } from "../../api/documents";

export function ArchiveFilters({
  filters,
  onChange,
}: {
  filters: DocumentListFilters;
  onChange: (next: DocumentListFilters) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(filters);

  const hasActiveFilters = Boolean(filters.type || filters.issuer || filters.from || filters.to);

  function handleApply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onChange({ ...filters, ...draft, offset: 0 });
    setOpen(false);
  }

  function handleClear() {
    const cleared: DocumentListFilters = {
      ...filters,
      type: undefined,
      issuer: undefined,
      from: undefined,
      to: undefined,
      offset: 0,
    };
    setDraft(cleared);
    onChange(cleared);
    setOpen(false);
  }

  return (
    <div className="flex flex-1 flex-wrap items-center gap-2">
      <label htmlFor="archive-search" className="sr-only">
        Tìm theo tên, số văn bản
      </label>
      <Input
        id="archive-search"
        type="search"
        placeholder="Tìm theo tên, số văn bản..."
        className="max-w-sm"
        defaultValue={filters.query ?? ""}
        onChange={(event) => onChange({ ...filters, query: event.target.value, offset: 0 })}
      />

      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) setDraft(filters);
        }}
      >
        <DialogTrigger asChild>
          <Button variant="secondary" size="sm">
            <SlidersHorizontal aria-hidden="true" size={15} />
            Lọc
          </Button>
        </DialogTrigger>
        <DialogContent title="Lọc văn bản">
          <form className="flex flex-col gap-4" onSubmit={handleApply}>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="filter-issuer" className="text-sm font-medium text-mg-text">
                Cơ quan ban hành
              </label>
              <Input
                id="filter-issuer"
                value={draft.issuer ?? ""}
                onChange={(event) => setDraft({ ...draft, issuer: event.target.value })}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label htmlFor="filter-type" className="text-sm font-medium text-mg-text">
                Loại văn bản
              </label>
              <Input
                id="filter-type"
                value={draft.type ?? ""}
                onChange={(event) => setDraft({ ...draft, type: event.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <label htmlFor="filter-from" className="text-sm font-medium text-mg-text">
                  Từ ngày
                </label>
                <Input
                  id="filter-from"
                  type="date"
                  value={draft.from ?? ""}
                  onChange={(event) => setDraft({ ...draft, from: event.target.value })}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <label htmlFor="filter-to" className="text-sm font-medium text-mg-text">
                  Đến ngày
                </label>
                <Input
                  id="filter-to"
                  type="date"
                  value={draft.to ?? ""}
                  onChange={(event) => setDraft({ ...draft, to: event.target.value })}
                />
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={handleClear}>
                Xóa bộ lọc
              </Button>
              <Button type="submit">Áp dụng</Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {hasActiveFilters ? (
        <Button variant="link" size="sm" onClick={handleClear}>
          Xóa bộ lọc
        </Button>
      ) : null}
    </div>
  );
}
