import {useMemo, useState} from 'react';
import type {
    GridColDef,
    GridPaginationModel,
    GridRenderEditCellParams,
    GridRowId,
    GridRowSelectionModel,
} from '@mui/x-data-grid';
import {DataGrid} from '@mui/x-data-grid';
import {Box, Chip, MenuItem, TextField, Typography,} from '@mui/material';
import {useSnackbar} from 'notistack';
import {useUpdateTask} from '../../api/hooks';
import type {Task, User} from '../../types';
import type {TaskUpdateValues} from '../../schemas/task';
import {issueTypeOptions, priorityOptions} from '../../schemas/task';

type TasksTableProps = {
    tasks: Task[];
    users?: User[];
    loading?: boolean;
    selectedIds?: string[];
    onSelectionChange?: (selection: string[]) => void;
    onRowDoubleClick?: (task: Task) => void;
    checkboxSelection?: boolean;
    hideFooter?: boolean;
};

const SelectEditCell = (
    params: GridRenderEditCellParams<Task>,
    options: readonly string[],
) => (
    <TextField
        select
        value={params.value ?? ''}
        onChange={(event) =>
            params.api.setEditCellValue({
                id: params.id,
                field: params.field,
                value: event.target.value,
            })
        }
        fullWidth
    >
        {options.map((option) => (
            <MenuItem key={option} value={option}>
                {option}
            </MenuItem>
        ))}
    </TextField>
);

const NumberEditCell = (params: GridRenderEditCellParams<Task>) => (
    <TextField
        type="number"
        value={params.value ?? ''}
        onChange={(event) =>
            params.api.setEditCellValue({
                id: params.id,
                field: params.field,
                value: event.target.value === '' ? undefined : Number(event.target.value),
            })
        }
        fullWidth
    />
);

export const TasksTable = ({
                               tasks,
                               users = [],
                               loading,
                               selectedIds = [],
                               onSelectionChange,
                               onRowDoubleClick,
                               checkboxSelection = true,
                               hideFooter = false,
                           }: TasksTableProps) => {
    const {enqueueSnackbar} = useSnackbar();
    const updateTask = useUpdateTask();
    const [paginationModel, setPaginationModel] = useState<GridPaginationModel>({
        pageSize: 20,
        page: 0,
    });
    const selectionModel = useMemo<GridRowSelectionModel>(
        () => ({
            type: 'include',
            ids: new Set<GridRowId>(selectedIds as GridRowId[]),
        }),
        [selectedIds],
    );

    const columns: GridColDef<Task>[] = [
        {
            field: 'summary',
            headerName: 'Summary',
            flex: 1.4,
            editable: true,
        },
        {
            field: 'assigneeId',
            headerName: 'Assignee',
            flex: 1,
            editable: true,
            renderCell: (params) => (
                <Box sx={{display: 'flex', alignItems: 'center', height: '100%'}}>
                    <Typography variant="body2">
                        {users.find((user) => user.id === params.value)?.displayName ?? 'Unassigned'}
                    </Typography>
                </Box>
            ),
            renderEditCell: (params) => (
                <TextField
                    select
                    value={params.value ?? ''}
                    onChange={(event) =>
                        params.api.setEditCellValue({
                            id: params.id,
                            field: params.field,
                            value: event.target.value || undefined,
                        })
                    }
                    fullWidth
                >
                    <MenuItem value="">Unassigned</MenuItem>
                    {users.map((user) => (
                        <MenuItem key={user.id} value={user.id}>
                            {user.displayName}
                        </MenuItem>
                    ))}
                </TextField>
            ),
        },
        {
            field: 'issueType',
            headerName: 'Issue type',
            flex: 0.6,
            editable: true,
            renderEditCell: (params) => SelectEditCell(params, issueTypeOptions),
        },
        {
            field: 'priority',
            headerName: 'Priority',
            flex: 0.5,
            editable: true,
            renderEditCell: (params) => SelectEditCell(params, priorityOptions),
        },
        {
            field: 'storyPoints',
            headerName: 'Points',
            type: 'number',
            width: 90,
            editable: true,
            renderEditCell: NumberEditCell,
        },
        {
            field: 'status',
            headerName: 'Status',
            flex: 0.5,
            renderCell: (params) => (
                <Chip
                    label={params.value}
                    size="small"
                    color={
                        params.value === 'approved'
                            ? 'success'
                            : params.value === 'rejected'
                                ? 'error'
                                : 'default'
                    }
                />
            ),
        },
    ];

    const processRowUpdate = async (newRow: Task, oldRow: Task) => {
        const changes: Partial<TaskUpdateValues> = {};
        if (newRow.summary !== oldRow.summary) changes.summary = newRow.summary;
        if (newRow.assigneeId !== oldRow.assigneeId)
            changes.assigneeId = newRow.assigneeId;
        if (newRow.issueType !== oldRow.issueType) changes.issueType = newRow.issueType;
        if (newRow.priority !== oldRow.priority) changes.priority = newRow.priority;
        if (newRow.storyPoints !== oldRow.storyPoints)
            changes.storyPoints = newRow.storyPoints;
        if (Object.keys(changes).length === 0) {
            return oldRow;
        }

        await new Promise((resolve) => setTimeout(resolve, 300));

        try {
            const updated = await updateTask.mutateAsync({
                id: newRow.id,
                data: changes,
            });
            enqueueSnackbar('Task updated', {variant: 'success'});
            return {...oldRow, ...updated};
        } catch (error) {
            enqueueSnackbar((error as Error).message, {variant: 'error'});
            throw error;
        }
    };

    return (
        <DataGrid
            rowHeight={68}
            columnHeaderHeight={62}
            rows={tasks}
            columns={columns}
            loading={loading}
            checkboxSelection={checkboxSelection}
            disableRowSelectionOnClick
            processRowUpdate={processRowUpdate}
            onProcessRowUpdateError={(error) =>
                enqueueSnackbar(error.message ?? 'Failed to update', {variant: 'error'})
            }
            rowSelectionModel={selectionModel}
            onRowSelectionModelChange={(model) =>
                onSelectionChange?.(Array.from(model.ids, (id) => id.toString()))
            }
            paginationMode="client"
            paginationModel={paginationModel}
            onPaginationModelChange={setPaginationModel}
            pageSizeOptions={[10, 20, 50]}
            hideFooter={hideFooter}
            hideFooterPagination={hideFooter}
            hideFooterSelectedRowCount={hideFooter}
            sx={(theme) => ({
                backgroundColor: 'transparent',
                border: 'none',
                borderRadius: 3,
                height: '100%',
                '.MuiDataGrid-columnHeaders': {
                    backgroundColor:
                        theme.palette.mode === 'light'
                            ? 'rgba(15,23,42,0.03)'
                            : 'rgba(255,255,255,0.03)',
                    borderBottom: 'none',
                    borderRadius: 16,
                },
                '.MuiDataGrid-cell': {
                    borderBottom: `1px solid ${theme.palette.divider}`,
                },
            })}
            onRowDoubleClick={(params) =>
                onRowDoubleClick?.(params.row as Task)
            }
            onColumnHeaderClick={(params, event) => {
                if (params.field === '__check__') {
                    event.preventDefault();
                    const allIds = tasks.map((t) => t.id);
                    const nextSelection =
                        selectedIds.length === tasks.length ? [] : allIds;
                    onSelectionChange?.(nextSelection);
                }
            }}
            slots={{
                noRowsOverlay: () => (
                    <Typography variant="body2" sx={{p: 2}}>
                        No tasks found
                    </Typography>
                ),
            }}
        />
    );
};
